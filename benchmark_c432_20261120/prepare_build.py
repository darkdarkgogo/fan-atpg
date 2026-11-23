from pathlib import Path
import shutil, subprocess, re, json, hashlib, sys

out = Path(__file__).resolve().parent
base = Path.home() / 'fan-podem-c432-20261120'
base.mkdir(exist_ok=True)
src = out.parent / 'FAN_ATPG'
fan = base / 'fan'
shutil.copytree(src, fan, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))
podem = base / 'podem'
podem.mkdir(exist_ok=True)
podem_src = out.parent.parent / 'fault-reorder/reorderATPG/PODEM/src'
for p in podem_src.iterdir():
    if p.suffix in ('.cpp', '.h') and p.name != 'python_bindings.cpp':
        shutil.copy2(p, podem / p.name)
for root in (fan, podem):
    for p in root.rglob('*'):
        if p.is_file() and (p.suffix in ('.cpp','.h','.mk','.l','.y','.sh') or p.name == 'Makefile'):
            p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
main = podem / 'main.cpp'
main_text = main.read_text().replace('#include "atpg.h"', '#include "atpg.h"\n#include <chrono>')
main_text = main_text.replace('atpg.test(); // atpg.cpp', '''const auto bench_start = std::chrono::steady_clock::now();
        atpg.test(); // atpg.cpp
        fprintf(stdout, "[BENCH] ATPG seconds=%.9f\\n", std::chrono::duration<double>(std::chrono::steady_clock::now()-bench_start).count());''')
main.write_text(main_text)

bench_src = out.parent.parent / 'fault-reorder/artifacts/backtrack3000/bench-default/c432_binary.bench'
text = bench_src.read_text()
lines=[]
for line in text.splitlines():
    m=re.fullmatch(r'(\w+)\s*=\s*XOR\((\w+),(\w+)\)',line.strip())
    if m:
        z,a,b=m.groups(); n1,n2,n3=[f'cmp_{z}_{i}' for i in range(3)]
        lines += [f'{n1} = NAND({a},{b})',f'{n2} = NAND({a},{n1})',f'{n3} = NAND({b},{n1})',f'{z} = NAND({n2},{n3})']
    else: lines.append(line)
bench='\n'.join(lines)+'\n'
(out/'c432_common.bench').write_text(bench)
inputs=re.findall(r'^INPUT\((\w+)\)',bench,re.M)
outputs=re.findall(r'^OUTPUT\((\w+)\)',bench,re.M)
gates=[(m[1],m[2],m[3].split(',')) for m in re.finditer(r'^(\w+)\s*=\s*(\w+)\(([^)]+)\)',bench,re.M)]
wires=[g[0] for g in gates if g[0] not in outputs]
v=['module c432 ('+', '.join(inputs+outputs)+');','input '+', '.join(inputs)+';','output '+', '.join(outputs)+';','wire '+', '.join(wires)+';']
for i,(z,op,pins) in enumerate(gates):
    mapping=[f'.A{j}({p})' for j,p in enumerate(pins)]+[f'.Z({z})']
    v.append(f'C_{op}{len(pins)} g{i} ('+', '.join(mapping)+');')
v.append('endmodule')
(out/'c432_common.v').write_text('\n'.join(v)+'\n')
mdt=['array_delimiter = "[]";']
for op,n in sorted({(op,len(pins)) for _,op,pins in gates}):
    pins=[f'A{i}' for i in range(n)]
    prim={'NOT':'inv','NAND':'nand','NOR':'nor','AND':'and'}[op]
    mdt += [f'model C_{op}{n}', '('+', '.join(pins+['Z'])+')','(']
    mdt += [f' input ({p}) ( )' for p in pins]
    mdt += [' output (Z) (',f' primitive = _{prim} p ('+', '.join(pins+['Z'])+');',')',')']
(out/'common.mdt').write_text('\n'.join(mdt)+'\n')
script='''read_lib common.mdt
read_netlist c432_common.v
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
for name in ('c432_common.bench','c432_common.v','common.mdt','fan.script'):
    shutil.copy2(out/name,base/name)
(out/'input_info.json').write_text(json.dumps({'inputs':len(inputs),'outputs':len(outputs),'gates':len(gates),'bench_sha256':hashlib.sha256(bench.encode()).hexdigest(),'linux_dir':str(base)},indent=2))
print('prepared',len(inputs),len(outputs),len(gates),flush=True)
if '--prepare-only' in sys.argv:
    raise SystemExit(0)
with (out/'fan_build.log').open('w') as log:
    p=subprocess.run(['make'],cwd=fan,stdout=log,stderr=subprocess.STDOUT)
if p.returncode:
    print((out/'fan_build.log').read_text()[-6000:]); raise SystemExit(p.returncode)
print('FAN built',flush=True)
with (out/'podem_build.log').open('w') as log:
    p=subprocess.run(['g++','-std=c++11','-O3',*map(str,sorted(podem.glob('*.cpp'))),'-o',str(podem/'atpg')],stdout=log,stderr=subprocess.STDOUT)
if p.returncode:
    print((out/'podem_build.log').read_text()[-6000:]); raise SystemExit(p.returncode)
print('PODEM built',flush=True)
for name,cmd in [('fan',[str(fan/'bin/opt/fan'),'-f','fan.script']),('podem',[str(podem/'atpg'),'-bt','500','-seed','0','c432_common.bench'])]:
    p=subprocess.run(cmd,cwd=base,capture_output=True,text=True,timeout=60)
    (out/f'{name}_warmup.log').write_text(p.stdout+p.stderr)
    print(name,p.returncode,(p.stdout+p.stderr)[-2500:],flush=True)
