"""Linux native CLI read/build checks, with no full ATPG run."""
import json
from pathlib import Path
import subprocess
import argparse

root=Path(__file__).resolve().parents[2]
fan=root/'FAN_ATPG'
results=[]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--test-dir',type=Path,default=fan/'netlist/test')
args=parser.parse_args()
for netlist in sorted(args.test_dir.resolve().iterdir()):
    if netlist.suffix.lower() not in ('.v','.sv') or not netlist.is_file(): continue
    c=netlist.stem
    script=root/'datasets/itc99_nangate45/logs'/(c+'_load.script')
    script.write_text('read_lib techlib/mod_nangate45.mdt\nread_netlist '+str(netlist)+'\n'
                      'report_netlist\nbuild_circuit --frame 1\nreport_circuit\nexit\n')
    proc=subprocess.run([str(fan/'bin/opt/fan'),'-f',str(script)],cwd=fan,capture_output=True,text=True,timeout=60)
    log=proc.stdout+proc.stderr
    script.with_suffix('.log').write_text(log)
    ok=proc.returncode==0 and '**ERROR' not in log and 'Finished building circuit' in log
    results.append(dict(circuit=c,passed=ok,returncode=proc.returncode))
    print(c,ok,flush=True)
(root/'datasets/itc99_nangate45/validation_cli_load.json').write_text(json.dumps(results,indent=2)+'\n')
assert results and all(r['passed'] for r in results)
