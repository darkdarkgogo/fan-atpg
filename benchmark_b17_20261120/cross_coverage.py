from pathlib import Path
import re, json, subprocess, shutil, time

out=Path(__file__).resolve().parent
base=Path.home()/'fan-podem-b17-20261120'
bins=Path.home()/'fan-podem-c432-20261120'
s=(out/'b17_common.bench').read_text()
ins=re.findall(r'^INPUT\((\w+)\)',s,re.M)
outs=re.findall(r'^OUTPUT\((\w+)\)',s,re.M)
gs=[(m[1],m[2],m[3].split(',')) for m in re.finditer(r'^(\w+)\s*=\s*(\w+)\(([^)]+)\)',s,re.M)]
info=json.loads((out/'input_info.json').read_text())
aliases=info['output_aliases']
v=(out/'b17_common.v').read_text()
vg=[]
for m in re.finditer(r'^C_(\w+)(\d) g\d+ \(([^;]+)\);',v,re.M):
    mapping=dict(re.findall(r'\.(\w+)\((\w+)\)',m[3]))
    vg.append((mapping['Z'],m[1],[mapping[f'A{i}'] for i in range(int(m[2]))]))
assert gs==vg,'BENCH and Verilog gate connectivity mismatch'
assert dict(re.findall(r'^assign (\w+) = (\w+);',v,re.M))==aliases

fan_text=(out/'fan_0.pat').read_text()
fan_lines=fan_text.splitlines()
fan_ins=fan_lines[0].split('|')[0].split()
fan_outs=fan_lines[2].split()
fan_records=re.findall(r'^_pattern_\d+\s+([01]+)\s*\|([^\n]+)',fan_text,re.M)
input_indices=[fan_ins.index(x) for x in ins]
fan_patterns=[''.join(p[i] for i in input_indices) for p,_ in fan_records]
podem_text=re.sub(r'\[ATPG\][^\n]*\n','',(out/'PODEM_0.log').read_text())
(out/'PODEM_0_stdout.log').write_text(podem_text)
podem_patterns=re.findall(r"^T'([01]+)'",podem_text,re.M)
runs={x['tool']:x for x in json.loads((out/'runs.json').read_text())}
assert len(fan_patterns)==runs['FAN_ATPG']['patterns']
assert len(podem_patterns)==runs['PODEM']['patterns']

def logic_sim(patterns):
    assert patterns and all(len(p)==len(ins) for p in patterns)
    mask=(1<<len(patterns))-1
    values={name:int(''.join(p[i] for p in reversed(patterns)),2) for i,name in enumerate(ins)}
    for z,op,pins in gs:
        if op in ('NOT','BUF'): value=values[pins[0]]
        elif op in ('AND','NAND'):value=values[pins[0]]&values[pins[1]]
        elif op in ('OR','NOR'):value=values[pins[0]]|values[pins[1]]
        else:raise ValueError(op)
        if op in ('NOT','NAND','NOR'):value^=mask
        values[z]=value
    return values

fan_values=logic_sim(fan_patterns)
for i,(_,tail) in enumerate(fan_records):
    expected=tail.split('|')[3].strip()
    assert len(expected)==len(fan_outs),(i,len(expected),len(fan_outs))
    for j,name in enumerate(fan_outs):
        actual=str((fan_values[aliases[name]]>>i)&1)
        assert expected[j] in (actual,'X'),(i,name,expected[j],actual)
print('Verified BENCH/Verilog structure and all FAN good-circuit outputs',flush=True)

podem_values=logic_sim(podem_patterns)
header=' '.join(ins)+' |\n |\n'+' '.join(aliases)+'\nBASIC_SCAN\n_num_of_pattern_'+str(len(podem_patterns))+'\n'
with (out/'podem.pat').open('w') as f:
    f.write(header)
    for i,p in enumerate(podem_patterns):
        output=''.join(str((podem_values[x]>>i)&1) for x in outs)
        f.write(f'_pattern_{i+1} {p} |  |  |  | {output} |  |\n')
results={'gate_connectivity_verified':True,'all_fan_good_outputs_verified':True,'method':'FAN_ATPG standalone parallel-pattern fault simulation on the identical fault list'}
for tool,filename in [('FAN_ATPG','fan_0.pat'),('PODEM','podem.pat')]:
    shutil.copy2(out/filename,base/filename)
    script=f'''read_lib common.mdt
read_netlist b17_common.v
build_circuit --frame 1
set_fault_type saf
add_fault --all
read_pattern {filename}
run_fault_sim -m pp
report_statistics
exit
'''
    (base/'fsim.script').write_text(script)
    start=time.perf_counter()
    print('START common fsim',tool,flush=True)
    p=subprocess.run([str(bins/'fan/bin/opt/fan'),'-f','fsim.script'],cwd=base,capture_output=True,text=True,timeout=1200)
    text=p.stdout+p.stderr
    (out/f'{tool}_common_fsim.log').write_text(text)
    (out/f'{tool}_fsim.script').write_text(script)
    assert p.returncode==0 and '**ERROR' not in text,text[-4000:]
    full=int(re.search(r'FU \(full\)\s+(\d+)',text)[1])
    detected=int(re.search(r'DT \(detected\)\s+(\d+)',text)[1])
    results[tool]={'total':full,'detected':detected,'coverage_percent':100*detected/full,'verification_seconds':time.perf_counter()-start}
    print(tool,results[tool],flush=True)
    (out/'common_coverage.json').write_text(json.dumps(results,indent=2))
