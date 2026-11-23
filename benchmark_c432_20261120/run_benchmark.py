from pathlib import Path
import subprocess, re, time, statistics, json, shutil, random, csv

out=Path(__file__).resolve().parent
base=Path.home()/'fan-podem-c432-20261120'
commands={'FAN_ATPG':[str(base/'fan/bin/opt/fan'),'-f','fan.script'],
          'PODEM':[str(base/'podem/atpg'),'-bt','500','-seed','0','c432_common.bench']}
def run(name, index):
    start=time.perf_counter()
    p=subprocess.run(commands[name],cwd=base,capture_output=True,text=True,timeout=120)
    wall=time.perf_counter()-start
    s=p.stdout+p.stderr
    (out/f'{name}_{index}.log').write_text(s)
    if p.returncode or '**ERROR' in s or 'ATPG failed' in s:
        raise RuntimeError(s[-7000:])
    if name=='FAN_ATPG':
        core=float(re.search(r'Finished pattern generation\s+([\d.e+-]+) s',s)[1])
        patterns=int(re.search(r'#Patterns\s+(\d+)',s)[1])
        coverage=float(re.search(r'fault coverage\s+([\d.]+)%',s)[1])
        shutil.copy2(base/'fan.pat',out/'fan.pat')
    else:
        core=float(re.search(r'\[BENCH\] ATPG seconds=([\d.]+)',s)[1])
        patterns=int(re.search(r'number of test vectors = (\d+)',s)[1])
        coverage=float(re.search(r'total gate fault coverage = ([\d.]+)%',s)[1])
    return dict(tool=name,repeat=index,wall_seconds=wall,atpg_seconds=core,patterns=patterns,reported_coverage_percent=coverage)

for name in commands: print('warmup',run(name,'warmup'),flush=True)
rows=[]
for i in range(11):
    for name in (list(commands) if i%2==0 else list(reversed(commands))):
        row=run(name,i); rows.append(row); print(row,flush=True)
with (out/'timings.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
summary={}
for name in commands:
    values=[r for r in rows if r['tool']==name]
    summary[name]={key:statistics.median(r[key] for r in values) for key in ['wall_seconds','atpg_seconds','patterns','reported_coverage_percent']}
    summary[name]['atpg_min_seconds']=min(r['atpg_seconds'] for r in values)
    summary[name]['atpg_max_seconds']=max(r['atpg_seconds'] for r in values)
(out/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2),flush=True)
