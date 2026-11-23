from pathlib import Path
import re, json, random, functools

out=Path(__file__).resolve().parent
def load(path):
    s=path.read_text()
    return (re.findall(r'^INPUT\((\w+)\)',s,re.M),re.findall(r'^OUTPUT\((\w+)\)',s,re.M),
            [(m[1],m[2],m[3].split(',')) for m in re.finditer(r'^(\w+)\s*=\s*(\w+)\(([^)]+)\)',s,re.M)])
inputs,outputs,gates=load(out/'c432_common.bench')
def evaluate(ins,outs,gs,values,mask,fault=None):
    v=dict(zip(ins,values))
    if fault and fault[0]=='stem' and fault[1] in v: v[fault[1]]=mask if fault[-1] else 0
    for i,(z,op,pins) in enumerate(gs):
        args=[v[p] for p in pins]
        if fault and fault[0]=='pin' and fault[1]==i: args[fault[2]]=mask if fault[-1] else 0
        if op in ('AND','NAND'): result=functools.reduce(int.__and__,args)
        elif op in ('OR','NOR'): result=functools.reduce(int.__or__,args)
        elif op in ('XOR','XNOR'): result=functools.reduce(int.__xor__,args)
        elif op=='NOT': result=args[0]^mask
        elif op=='BUF': result=args[0]
        else: raise ValueError(op)
        if op in ('NAND','NOR','XNOR'): result^=mask
        if fault and fault[0]=='stem' and fault[1]==z: result=mask if fault[-1] else 0
        v[z]=result
    result=[v[p] for p in outs]
    if fault and fault[0]=='po': result[fault[1]]=mask if fault[-1] else 0
    return result

original=out.parent.parent/'fault-reorder/artifacts/backtrack3000/bench-original-default/c432.bench'
oi,oo,og=load(original)
assert oi==inputs and oo==outputs
rng=random.Random(0)
values=[rng.getrandbits(1024) for _ in inputs]
assert evaluate(inputs,outputs,gates,values,(1<<1024)-1)==evaluate(oi,oo,og,values,(1<<1024)-1)
sites=[('stem',p) for p in inputs+[z for z,_,_ in gates]]
sites += [('pin',i,j) for i,(_,_,pins) in enumerate(gates) for j in range(len(pins))]
sites += [('po',i) for i in range(len(outputs))]
faults=[(*site,sa) for site in sites for sa in (0,1)]
result={'random_equivalence_vectors':1024,'common_uncollapsed_faults':len(faults)}
fan_text=(out/'fan.pat').read_text()
fan_order=fan_text.splitlines()[0].split('|')[0].split()
fp=re.findall(r'^_pattern_\d+\s+([01]+)\s*\|',fan_text,re.M)
fp=[''.join(p[fan_order.index(x)] for x in inputs) for p in fp]
pp=re.findall(r"^T'([01]+)'",(out/'PODEM_0.log').read_text(),re.M)
for tool,patterns in [('FAN_ATPG',fp),('PODEM',pp)]:
    assert patterns and all(len(p)==len(inputs) for p in patterns)
    mask=(1<<len(patterns))-1
    values=[sum((int(p[j])<<i) for i,p in enumerate(patterns)) for j in range(len(inputs))]
    good=evaluate(inputs,outputs,gates,values,mask)
    detected=[]
    for fault in faults:
        bad=evaluate(inputs,outputs,gates,values,mask,fault)
        if any(a!=b for a,b in zip(good,bad)): detected.append(fault)
    result[tool]={'patterns':len(patterns),'detected':len(detected),'total':len(faults),'coverage_percent':100*len(detected)/len(faults)}
(out/'independent_coverage.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
