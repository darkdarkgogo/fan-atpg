"""Validate the imported netlists with the project's native Linux FAN CLI."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
data = root / 'datasets/itc99_nangate45'
fan = root / 'FAN_ATPG'
models = set(re.findall(r'^model\s+(\w+)', (fan / 'techlib/mod_nangate45.mdt').read_text(), re.M))
results = []
for c in ['b03', 'b04', 'b05', 'b07', 'b08', 'b09', 'b13']:
    netlist = fan / 'netlist' / (c + '_nangate45.v')
    src = netlist.read_text()
    cells = re.findall(r'^\s*(\w+_X\d+)\s+\w+\s*\(', src, re.M)
    assert set(cells) <= models, set(cells) - models
    script = data / 'logs' / (c + '.script')
    script.write_text('read_lib techlib/mod_nangate45.mdt\n'
                      f'read_netlist -v netlist/{c}_nangate45.v\n'
                      'report_netlist\nbuild_circuit --frame 1\nreport_circuit\n'
                      'set_fault_type saf\nadd_fault --all\n'
                      'set_static_compression on\nset_dynamic_compression on\n'
                      'set_X-Fill on\nrun_atpg\nreport_statistics\nexit\n')
    proc = subprocess.run(['stdbuf', '-oL', '-eL', str(fan / 'bin/opt/fan'), '-f', str(script)], cwd=fan,
                          capture_output=True, text=True, timeout=120)
    log = proc.stdout + proc.stderr
    (data / 'logs' / (c + '_fan.log')).write_text(log)
    ok = proc.returncode == 0 and '**ERROR' not in log and 'fault coverage' in log.lower()
    results.append(dict(circuit=c, netlist=str(netlist.relative_to(root)),
                        cells=len(cells), scan_ffs=sum(t.startswith('SDFF') for t in cells),
                        cell_types=sorted(set(cells)), sha256=hashlib.sha256(netlist.read_bytes()).hexdigest(),
                        fan_returncode=proc.returncode, passed=ok))
    print(c, 'PASS' if ok else 'FAIL', proc.returncode, flush=True)
    if not ok:
        print(log[-2500:], flush=True)
(data / 'validation.json').write_text(json.dumps(results, indent=2) + '\n')
assert all(r['passed'] for r in results)
