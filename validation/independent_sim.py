"""Independent bit-parallel simulation of the original FAN-exported circuit.

Reads exported primitive JSON, never BENCH, and never calls cpp_fan simulation.
"""
import argparse
from functools import reduce
import json
from pathlib import Path
import re


def read_circuit(source):
    if isinstance(source, dict):
        raw = source
    else:
        path = Path(source)
        if path.suffix.lower() != '.json':
            raise ValueError('Use exported native circuit/AIG graph JSON, not a netlist reader')
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
    raw = raw.get('native_circuit', raw)
    if raw.get('schema') != 'fan_circuit_graph_v1':
        raise ValueError('Expected original FAN circuit graph schema')
    inputs = list(raw['input_gate_ids']); outputs = list(raw['output_gate_ids'])
    records = {g['gate_id']: g for g in raw['gates']}
    if len(records) != len(raw['gates']) or not inputs or not outputs:
        raise ValueError('Invalid circuit gate IDs or boundaries')
    if not set(inputs + outputs) <= set(records):
        raise ValueError('Unknown boundary gate')
    known = set(inputs); pending = [g for g in raw['gates'] if g['gate_id'] not in known]; ordered=[]
    while pending:
        later=[]
        for gate in pending:
            if set(gate['fanins']) <= known:
                ordered.append(gate); known.add(gate['gate_id'])
            else:
                later.append(gate)
        if len(later) == len(pending):
            raise ValueError('Undefined fanin or cycle in native circuit')
        pending=later
    return inputs, outputs, ordered, list(raw['input_names']), records


def evaluate(circuit, values, mask, fault=None):
    inputs, outputs, gates, names, records = circuit
    signals = dict(zip(inputs, values))
    kind, target, pin, sa = fault if fault else (None, None, None, None)
    stuck = mask if sa else 0
    if kind == 'GO' and target in signals:
        signals[target] = stuck
    for gate in gates:
        node = gate['gate_id']; args=[signals[i] for i in gate['fanins']]
        if kind == 'GI' and node == target:
            args[pin] = stuck
        op = gate['kind'].upper()
        match = re.fullmatch(r'(AND|NAND|OR|NOR|XOR|XNOR)[234]?', op)
        if match:
            op=match[1]
        if op in ('AND','NAND'):
            value=reduce(int.__and__,args)
        elif op in ('OR','NOR'):
            value=reduce(int.__or__,args)
        elif op in ('XOR','XNOR'):
            value=reduce(int.__xor__,args)
        elif op in ('INV','NOT','BUF','BUFF','PO','PPO') and len(args)==1:
            value=args[0]
        elif op in ('TIE0','TIE1') and not args:
            value=mask if op=='TIE1' else 0
        else:
            raise ValueError('Unsupported independently simulated gate: '+op)
        if op in ('INV','NOT','NAND','NOR','XNOR'):
            value ^= mask
        signals[node] = stuck if kind=='GO' and node==target else value
    return [signals[i] for i in outputs]


def coverage(source, patterns, input_names=None):
    circuit=read_circuit(source)
    inputs, outputs, gates, names, records=circuit
    patterns=list(patterns); order=list(names if input_names is None else input_names)
    if len(order)!=len(names) or set(order)!=set(names):
        raise ValueError('Pattern input names disagree with original FAN circuit')
    if any(len(p)!=len(order) or set(p)-{'0','1'} for p in patterns):
        raise ValueError('Independent verification requires fully specified binary patterns')
    positions=[order.index(name) for name in names]
    values=[sum((int(p[j])<<k) for k,p in enumerate(patterns)) for j in positions]
    mask=(1<<len(patterns))-1; good=evaluate(circuit,values,mask)
    live={p for g in records.values() for p in g['fanins']}
    sites=[('GO',i,-1) for i in sorted(records) if i in live]
    sites += [('GI',i,j) for i,g in sorted(records.items()) for j in range(len(g['fanins']))]
    detected=[]
    for site in sites:
        for sa in (0,1):
            fault=(*site,sa)
            if evaluate(circuit,values,mask,fault)!=good:
                detected.append(fault)
    total=2*len(sites)
    return {'patterns':len(patterns),'detected':len(detected),'total':total,
            'coverage_percent':100*len(detected)/total if total else 0,
            'detected_faults':[list(f) for f in detected]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raw=json.loads(args.result.read_text(encoding='utf-8-sig'))
    result=coverage(args.graph,raw['test_vectors'],raw.get('input_names')); result.pop('detected_faults')
    if 'detected_equivalent_faults' in raw:
        result['native_detected']=raw['detected_equivalent_faults']; result['native_total']=raw['uncollapsed_faults']
        result['matches_native']=result['detected']==result['native_detected'] and result['total']==result['native_total']
        if not result['matches_native']:
            raise RuntimeError('Independent simulation disagrees: '+str(result))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
