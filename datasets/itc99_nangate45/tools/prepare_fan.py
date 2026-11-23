"""Convert scalar Yosys output to an explicit fullscan capture view.

Raw mapped netlists retain functional reset. Capture views tie asynchronous
controls inactive, as required during scan load/capture.
"""
import re
import sys
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[3]
data = root / 'datasets/itc99_nangate45'
circuit = sys.argv[1]
src = (data / 'raw' / (circuit + '.v')).read_text()
escaped = set(re.findall(r'\\([^\s]+)\s', src))
mapping = {n: re.sub(r'[^a-zA-Z0-9_$]', '_', n) for n in escaped}
assert len(set(mapping.values())) == len(mapping), 'identifier collision'
src = re.sub(r'\\([^\s]+)\s', lambda m: mapping[m[1]] + ' ', src)
for clock in ('clock', 'CLOCK', 'clk', 'CLK'):
    src = re.sub(r'\b' + clock + r'\b', 'CK', src)
assert not re.search(r'\b(?:input|output|wire)\s+\[', src), 'splitnets -ports required'
refs = Counter(re.findall(r'\b\w+\b', src))
def drop_dead_unknown(m):
    assert refs[m[1]] == 2, 'live unknown assignment: ' + m[1]
    return ''
src = re.sub(r"^\s*assign\s+(\w+)\s*=\s*1'[hb][xXzZ]\s*;", drop_dead_unknown, src, flags=re.M)
used_constants = set()
def constant(m):
    assert m[1] == '1' and m[3] in ('0', '1'), 'unknown/multibit literal'
    value = int(m[3])
    used_constants.add(value)
    return f'fan_const{value}'
src = re.sub(r"(\d+)'([bBhHdDoO])([0-9a-fA-FxXzZ_]+)", constant, src)
cells = []
for m in re.finditer(r'^\s*(\w+_X\d+)\s+(\w+)\s*\((.*?)\);', src, re.M | re.S):
    pins = dict(re.findall(r'\.(\w+)\(\s*(\w+)\s*\)', m[3]))
    cells.append([m[1], m[2], pins])
assert cells and all(not t.startswith('SDFF') for t, _, _ in cells)
counts = Counter(re.findall(r'\b\w+\b', src))
extra, ffs = [], []
for cell in cells:
    typ, name, pins = cell
    if typ.startswith('DFF'):
        assert typ in ('DFFR_X1', 'DFFR_X2', 'DFFRS_X1', 'DFFRS_X2', 'DFFS_X1', 'DFFS_X2', 'DFF_X1', 'DFF_X2'), typ
        qn = pins.pop('QN', None)
        if qn and counts[qn] > 2:
            extra.append(['INV_X1', f'fan_qn_{len(extra)}', {'A': pins['Q'], 'ZN': qn}])
        for control in ('RN', 'SN'):
            if control in pins:
                pins[control] = 'fan_const1'
                used_constants.add(1)
        cell[0] = 'S' + typ
        ffs.append(cell)
ffs.sort(key=lambda c: c[1])
assert ffs
prev = 'test_si'
for _, _, pins in ffs:
    pins.update(SE='test_se', SI=prev)
    prev = pins['Q']
cells.extend(extra)
for value in sorted(used_constants):
    cells.append([f'LOGIC{value}_X1', f'fan_tie{value}', {'Z': f'fan_const{value}'}])
inputs = re.findall(r'^\s*input\s+(\w+)\s*;', src, re.M)
outputs = re.findall(r'^\s*output\s+(\w+)\s*;', src, re.M)
aliases = re.findall(r'^\s*assign\s+(\w+)\s*=\s*(\w+)\s*;', src, re.M)
aliases.append(('test_so', prev))
drivers = {}
for i, (_, _, pins) in enumerate(cells):
    for pin in ('Z', 'ZN', 'Q'):
        if pin in pins:
            drivers[pins[pin]] = i
alias_map = dict(aliases)
live, nets, pending = set(), set(), outputs + ['test_so']
while pending:
    net = pending.pop()
    if net in nets:
        continue
    nets.add(net)
    if net in alias_map:
        pending.append(alias_map[net])
    if net in drivers:
        i = drivers[net]
        if i not in live:
            live.add(i)
            pending.extend(v for k, v in cells[i][2].items() if k not in ('Z', 'ZN', 'Q'))
assert {ff[1] for ff in ffs} <= {cells[i][1] for i in live}, 'lost scan FF'
cells = [cell for i, cell in enumerate(cells) if i in live]
aliases = [(a, b) for a, b in aliases if a in nets]
inputs = [n for n in inputs if n in nets] + ['test_si', 'test_se']
outputs += ['test_so']
declarations = ['input ' + n + ';' for n in inputs] + ['output ' + n + ';' for n in outputs]
all_nets = {n for _, _, pins in cells for n in pins.values()} | {n for a in aliases for n in a}
declarations += ['wire ' + n + ';' for n in sorted(all_nets - set(inputs + outputs))]
body = ['  ' + t + ' ' + n + ' (' + ', '.join('.' + k + '(' + v + ')' for k, v in pins.items()) + ');' for t, n, pins in cells]
body += ['  assign ' + a + ' = ' + b + ';' for a, b in aliases]
out = '// Nangate45 fullscan capture view; async RN/SN tied inactive. Raw functional netlist retained.\n'
out += 'module ' + circuit + '(' + ', '.join(inputs + outputs) + ');\n'
out += '\n'.join(declarations + body) + '\nendmodule\n'
directory=root/'FAN_ATPG/netlist'
if (directory/'test'/(circuit+'_nangate45.v')).exists():
    directory=directory/'test'
(directory / (circuit + '_nangate45.v')).write_text(out)
print(circuit, len(cells), 'cells', len(ffs), 'scan FFs', flush=True)
