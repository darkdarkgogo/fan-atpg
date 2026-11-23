"""Deterministic lowering of FAN native Circuit IDs; never parses netlists."""
import copy
import hashlib
import heapq
import itertools
import json
import random
import re


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def native_circuit_digest(native):
    return object_digest(native)


def graph_digest(graph):
    return object_digest({k: v for k, v in graph.items() if k != 'graph_sha256'})


def _ordered_gates(native):
    if native.get('schema') != 'fan_circuit_graph_v1':
        raise ValueError('Unsupported native FAN circuit schema')
    gates = native['gates']
    if [g['gate_id'] for g in gates] != list(range(len(gates))):
        raise ValueError('Native gate IDs must be contiguous and ordered')
    children, remaining = [[] for _ in gates], []
    for gate in gates:
        pins = gate['fanins']
        for pin in pins:
            if type(pin) is not int or not 0 <= pin < len(gates):
                raise ValueError('Invalid native fanin ID')
            children[pin].append(gate['gate_id'])
        remaining.append(len(pins))
        kind = gate['kind']
        match = re.fullmatch(r'(AND|NAND|OR|NOR|XOR|XNOR)([234])', kind)
        arity = int(match[2]) if match else {'PI': 0, 'PO': 1, 'INV': 1, 'BUF': 1, 'TIE0': 0, 'TIE1': 0}.get(kind)
        if arity is None or kind in ('XOR4', 'XNOR4') or len(pins) != arity:
            raise ValueError('Unsupported native gate kind or arity: ' + kind)
    for port, kind in (('input', 'PI'), ('output', 'PO')):
        ids = native[port + '_gate_ids']
        if len(ids) != len(native[port + '_names']) or len(ids) != len(set(ids)):
            raise ValueError('Invalid native boundary ports')
        if set(ids) != {g['gate_id'] for g in gates if g['kind'] == kind}:
            raise ValueError('Native boundary gate IDs disagree')
    queue = [i for i, count in enumerate(remaining) if count == 0]
    heapq.heapify(queue)
    ordered = []
    while queue:
        index = heapq.heappop(queue)
        ordered.append(gates[index])
        for child in children[index]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(queue, child)
    if len(ordered) != len(gates):
        raise ValueError('Native circuit contains a combinational cycle')
    return ordered


def lower_native_circuit(native):
    ordered = _ordered_gates(native)
    nodes, edges, anchors = [], [], {}
    def add(kind, pins):
        index = len(nodes)
        nodes.append({'id': index, 'name': 'aig_' + str(index), 'kind': kind, 'inputs': list(pins),
                      'origin': None, 'level': 0 if not pins else 1 + max(nodes[p]['level'] for p in pins)})
        edges.extend([p, index] for p in pins)
        return index
    def inv(a):
        return add('NOT', [a])
    def and_(a, b):
        return add('AND', [a, b])
    def xor(a, b):
        return inv(and_(inv(and_(a, inv(b))), inv(and_(inv(a), b))))
    for gate_id in native['input_gate_ids']:
        name = 'g' + str(gate_id)
        anchors[name] = add('INPUT', [])
        nodes[anchors[name]]['origin'] = name
    for gate in ordered:
        name, kind = 'g' + str(gate['gate_id']), gate['kind']
        if kind == 'PI':
            continue
        pins = [anchors['g' + str(p)] for p in gate['fanins']]
        if kind in ('TIE0', 'TIE1'):
            if not native['input_gate_ids']:
                raise ValueError('Constant-only circuits require a real PI for the pinned encoder')
            pi = anchors['g' + str(native['input_gate_ids'][0])]
            result = and_(pi, inv(pi))
            if kind == 'TIE1':
                result = inv(result)
        elif kind in ('BUF', 'PO'):
            result = inv(inv(pins[0]))
        elif kind == 'INV':
            result = inv(pins[0])
        else:
            family = kind.rstrip('234')
            if family in ('OR', 'NOR'):
                pins = [inv(p) for p in pins]
            result = pins[0]
            for pin in pins[1:]:
                result = xor(result, pin) if family in ('XOR', 'XNOR') else and_(result, pin)
            if family in ('NAND', 'OR', 'XNOR'):
                result = inv(result)
        nodes[result]['origin'] = name
        anchors[name] = result
    graph = {'schema': 'fan_aig_graph_v1', 'native_circuit': copy.deepcopy(native),
             'native_circuit_sha256': native_circuit_digest(native), 'nodes': nodes, 'edges': edges, 'anchors': anchors,
             'inputs': ['g' + str(i) for i in native['input_gate_ids']],
             'outputs': ['g' + str(i) for i in native['output_gate_ids']]}
    graph['graph_sha256'] = graph_digest(graph)
    return graph


def validate_native_graph(graph):
    if graph.get('schema') != 'fan_aig_graph_v1':
        raise ValueError('Unsupported FAN AIG graph schema')
    if graph != lower_native_circuit(graph['native_circuit']):
        raise ValueError('FAN graph differs from deterministic native lowering')
    return graph['native_circuit']


def verify_native_equivalence(native, graph, vectors=256, seed=14):
    """Scalar every-gate truth table, exhaustive for <=8 PIs; sampled otherwise."""
    ordered, inputs = _ordered_gates(native), native['input_gate_ids']
    rng = random.Random(seed)
    patterns = itertools.product((False, True), repeat=len(inputs)) if len(inputs) <= 8 else (
        [bool(rng.getrandbits(1)) for _ in inputs] for _ in range(vectors))
    for pattern in patterns:
        values = dict(zip(inputs, pattern))
        for gate in ordered:
            kind = gate['kind']
            if kind == 'PI':
                continue
            pins, family = [values[i] for i in gate['fanins']], kind.rstrip('234')
            if family in ('AND', 'NAND'):
                value = all(pins)
            elif family in ('OR', 'NOR'):
                value = any(pins)
            elif family in ('XOR', 'XNOR'):
                value = bool(sum(pins) % 2)
            elif kind in ('PO', 'BUF', 'INV'):
                value = pins[0]
            else:
                value = kind == 'TIE1'
            if family in ('NAND', 'NOR', 'XNOR', 'INV'):
                value = not value
            values[gate['gate_id']] = value
        aig_values = []
        for node in graph['nodes']:
            pins = [aig_values[p] for p in node['inputs']]
            value = values[int(node['origin'][1:])] if node['kind'] == 'INPUT' else (
                all(pins) if node['kind'] == 'AND' else not pins[0])
            aig_values.append(value)
        for gate_id, value in values.items():
            if aig_values[graph['anchors']['g' + str(gate_id)]] != value:
                raise ValueError('Native AIG equivalence mismatch at g' + str(gate_id))
