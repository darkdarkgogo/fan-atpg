from pathlib import Path
import re, json, shutil, subprocess, time, sys, hashlib

out=Path(__file__).resolve().parent
base=Path.home()/'fan-podem-b17-20261120'
bins=Path.home()/'fan-podem-c432-20261120'
source=out.parent.parent/'fault-reorder/reorderATPG/datasets/validation/b17_C.bench'
base.mkdir(exist_ok=True)

def prepare():
    text=source.read_text()
    ins=re.findall(r'^INPUT\((\w+)\)',text,re.M)
    outs=re.findall(r'^OUTPUT\((\w+)\)',text,re.M)
    gs=[(m[1],m[2],m[3].split(',')) for m in re.finditer(r'^(\w+)\s*=\s*(\w+)\(([^)]+)\)',text,re.M)]
    assert len(gs)==sum('=' in line and not line.startswith('#') for line in text.splitlines())
    known=set(ins)
    for z,op,pins in gs:
        assert op in ('AND','OR','NAND','NOR','NOT','BUF') and len(pins)<=4
        assert set(pins)<=known,(z,pins)
        assert z not in known
        known.add(z)
    assert set(outs)<=known
    vouts=[f'cmp_PO_{i}' for i in range(len(outs))]
    assert not set(vouts)&known
    wires=[z for z,_,_ in gs]
    v=['module b17_C ('+', '.join(ins+vouts)+');', 'input '+', '.join(ins)+';', 'output '+', '.join(vouts)+';', 'wire '+', '.join(wires)+';']
    v += [f'assign {alias} = {wire};' for alias,wire in zip(vouts,outs)]
    for i,(z,op,pins) in enumerate(gs):
        mapping=[f'.A{j}({p})' for j,p in enumerate(pins)]+[f'.Z({z})']
        v.append(f'C_{op}{len(pins)} g{i} ('+', '.join(mapping)+');')
    v.append('endmodule')
    mdt=['array_delimiter = "[]";']
    for op,n in sorted({(op,len(pins)) for _,op,pins in gs}):
        pins=[f'A{i}' for i in range(n)]
        prim={'NOT':'inv','BUF':'buf','AND':'and','NAND':'nand','OR':'or','NOR':'nor'}[op]
        mdt += [f'model C_{op}{n}', '('+', '.join(pins+['Z'])+')','(']
        mdt += [f' input ({p}) ( )' for p in pins]
        mdt += [' output (Z) (',f' primitive = _{prim} p ('+', '.join(pins+['Z'])+');',')',')']
    (out/'b17_common.bench').write_text(text)
    (out/'b17_common.v').write_text('\n'.join(v)+'\n')
    (out/'common.mdt').write_text('\n'.join(mdt)+'\n')
    script='''read_lib common.mdt
read_netlist b17_common.v
build_circuit --frame 1
report_circuit
set_fault_type saf
add_fault --all
set_static_compression off
set_dynamic_compression off
set_X-Fill on
run_atpg
report_statistics
write_pattern fan.pat
exit
'''
    (out/'fan.script').write_text(script)
    for name in ('b17_common.bench','b17_common.v','common.mdt','fan.script'):
        shutil.copy2(out/name,base/name)
    info={'source':str(source),'inputs':len(ins),'outputs':len(outs),'gates':len(gs),'sha256':hashlib.sha256(text.encode()).hexdigest(),'linux_dir':str(base),'binary_dir':str(bins),'output_aliases':dict(zip(vouts,outs))}
    (out/'input_info.json').write_text(json.dumps(info,indent=2))
    print({k:v for k,v in info.items() if k!='output_aliases'},flush=True)

def run(name,index):
    cmds={'FAN_ATPG':[str(bins/'fan/bin/opt/fan'),'-f','fan.script'], 'PODEM':[str(bins/'podem/atpg'),'-bt','500','-seed','0','b17_common.bench']}
    log=base/f'{name}_{index}.log'
    start=time.perf_counter()
    print('START',name,index,flush=True)
    try:
        with log.open('w') as f:
            p=subprocess.run(cmds[name],cwd=base,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
        wall=time.perf_counter()-start
    finally:
        shutil.copy2(log,out/log.name)
    s=log.read_text()
    if name=='PODEM':
        # stderr progress can be inserted in the middle of a buffered stdout
        # vector. Strip entire progress records to reconstruct stdout exactly.
        s=re.sub(r'\[ATPG\][^\n]*\n','',s)
        (out/f'PODEM_{index}_stdout.log').write_text(s)
    if p.returncode or '**ERROR' in s or 'ATPG failed' in s: raise RuntimeError(s[-6000:])
    if name=='FAN_ATPG':
        core=float(re.search(r'Finished pattern generation\s+([\d.e+-]+) s',s)[1])
        patterns=int(re.search(r'#Patterns\s+(\d+)',s)[1])
        coverage=float(re.search(r'fault coverage\s+([\d.]+)%',s)[1])
        full=int(re.search(r'FU \(full\)\s+(\d+)',s)[1])
        collapsed=int(re.search(r'FU \(collapsed\)\s+(\d+)',s)[1])
        detected=int(re.search(r'DT \(detected\)\s+(\d+)',s)[1])
        shutil.copy2(base/'fan.pat',out/f'fan_{index}.pat')
    else:
        core=float(re.search(r'\[BENCH\] ATPG seconds=([\d.]+)',s)[1])
        patterns=int(re.search(r'number of test vectors = (\d+)',s)[1])
        coverage=float(re.search(r'total gate fault coverage = ([\d.]+)%',s)[1])
        full=int(re.search(r'total number of gate faults \(uncollapsed\) = (\d+)',s)[1])
        collapsed=int(re.search(r'number of equivalent gate faults \(collapsed\) = (\d+)',s)[1])
        detected=int(re.search(r'total number of detected faults = (\d+)',s)[1])
    row=dict(tool=name,repeat=index,wall_seconds=wall,atpg_seconds=core,patterns=patterns,reported_coverage_percent=coverage,full_faults=full,collapsed_faults=collapsed,detected_faults=detected)
    path=out/'runs.json'
    rows=json.loads(path.read_text()) if path.exists() else []
    rows.append(row);path.write_text(json.dumps(rows,indent=2))
    print('DONE',json.dumps(row),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    else:run(sys.argv[1],int(sys.argv[2]) if len(sys.argv)>2 else 0)
