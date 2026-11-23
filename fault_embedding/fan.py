"""Strict FAN native catalog identities mapped by native gate IDs."""
import re
from .native_aig import (lower_native_circuit, native_circuit_digest, object_digest,
                         validate_native_graph, verify_native_equivalence)

SCHEMA = 'fan_verilog_embeddings_v1'
CATALOG_FIELDS = ('gate_id', 'fault_id', 'node_name', 'input_wire_name', 'io', 'input_index',
                  'input_occurrence', 'fault_type', 'eqv_fault_num')


def canonical_catalog(catalog):
    return {'faults': [{key: item[key] for key in CATALOG_FIELDS} for item in catalog['faults']],
            'uncollapsed_total': int(catalog['uncollapsed_total'])}


def catalog_digest(catalog):
    return object_digest(canonical_catalog(catalog))


def resolve_fan_faults(catalog, native, graph):
    if graph['native_circuit'] != native:
        raise ValueError('Native circuit snapshot disagrees with graph')
    records, seen = [], set()
    for row, item in enumerate(canonical_catalog(catalog)['faults']):
        fault_id, gate_id = item['fault_id'], item['gate_id']
        if type(gate_id) is not int or not 0 <= gate_id < len(native['gates']):
            raise ValueError('Invalid native fault gate ID')
        name = 'g' + str(gate_id)
        io, sa, pin = int(item['io']), int(item['fault_type']), int(item['input_index'])
        if fault_id in seen or item['node_name'] != name or io not in (0, 1) or sa not in (0, 1):
            raise ValueError('Invalid native fault identity')
        seen.add(fault_id)
        identity = name + (':GO' if io == 1 else ':GI' + str(pin)) + ':sa' + str(sa)
        if not re.fullmatch(re.escape(identity) + r'(?:@dup[1-9][0-9]*)?', fault_id):
            raise ValueError('Fault identity fields disagree: ' + fault_id)
        receiver = graph['anchors'][name]
        if io == 1:
            if pin != -1 or item['input_occurrence'] != -1 or item['input_wire_name'] != '-':
                raise ValueError('Invalid native GO fault')
            connected, source = receiver, name
        else:
            pins = native['gates'][gate_id]['fanins']
            if pin < 0 or pin >= len(pins) or item['input_wire_name'] != 'g' + str(pins[pin]):
                raise ValueError('GI fault does not identify an actual receiver pin')
            if item['input_occurrence'] != pins[:pin].count(pins[pin]):
                raise ValueError('GI input occurrence mismatch')
            source = 'g' + str(pins[pin])
            connected = graph['anchors'][source]
        if int(item['eqv_fault_num']) <= 0:
            raise ValueError('Invalid native equivalence count')
        records.append({'fault_id': fault_id, 'gate_id': gate_id, 'catalog_row': row,
                        'original_gate': name, 'source_signal': source, 'io': 'GO' if io == 1 else 'GI',
                        'original_pin_index': pin, 'input_occurrence': int(item['input_occurrence']),
                        'sa_value': sa, 'eqv_fault_num': int(item['eqv_fault_num']),
                        'gate_function_anchor_node': receiver, 'connected_function_anchor_node': connected})
    if not records or sum(f['eqv_fault_num'] for f in records) != int(catalog['uncollapsed_total']):
        raise ValueError('Native fault equivalence counts do not match total')
    return records
