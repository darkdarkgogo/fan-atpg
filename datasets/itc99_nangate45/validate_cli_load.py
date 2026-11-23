"""Linux native CLI read/build checks, with no full ATPG run."""
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[2]
fan=root/'FAN_ATPG'
results=[]
for c in ('b12','b15','b20','b21','b22'):
    script=root/'datasets/itc99_nangate45/logs'/(c+'_load.script')
    script.write_text('read_lib techlib/mod_nangate45.mdt\nread_netlist netlist/'+c+'_nangate45.v\n'
                      'report_netlist\nbuild_circuit --frame 1\nreport_circuit\nexit\n')
    proc=subprocess.run([str(fan/'bin/opt/fan'),'-f',str(script)],cwd=fan,capture_output=True,text=True,timeout=60)
    log=proc.stdout+proc.stderr
    script.with_suffix('.log').write_text(log)
    ok=proc.returncode==0 and '**ERROR' not in log and 'Finished building circuit' in log
    results.append(dict(circuit=c,passed=ok,returncode=proc.returncode))
    print(c,ok,flush=True)
(root/'datasets/itc99_nangate45/validation_cli_load.json').write_text(json.dumps(results,indent=2)+'\n')
assert all(r['passed'] for r in results)
