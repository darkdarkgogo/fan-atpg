"""Check Verilog/MDT circuit graphs and catalogs without feature inference or training."""

import argparse
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from fault_order_rl.data import load_manifest
    from fault_embedding.fan import canonical_catalog, lower_native_circuit, resolve_fan_faults

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    sys.path.insert(0, str(manifest.module_dir))
    native = importlib.import_module('cpp_fan')
    rows = []
    for index, spec in enumerate(manifest.circuits):
        circuit = dict(native.circuit_graph(str(spec.netlist_path), str(spec.library_path)))
        catalog = dict(native.catalog_stuck_at(str(spec.netlist_path), str(spec.library_path)))
        graph = lower_native_circuit(circuit)
        faults = resolve_fan_faults(catalog, circuit, graph)
        canonical_catalog(catalog)
        rows.append({'name': spec.name, 'native_gates': len(circuit['gates']),
                     'inputs': len(circuit['input_gate_ids']), 'outputs': len(circuit['output_gate_ids']),
                     'collapsed_faults': len(faults), 'uncollapsed_faults': catalog['uncollapsed_total']})
        if index < 3 or (index + 1) % 100 == 0 or index + 1 == len(manifest.circuits):
            print('Checked {}/{} Verilog circuits: {}'.format(index + 1, len(manifest.circuits), spec.name), flush=True)
    result = {'manifest': str(manifest.path), 'input_format': 'verilog',
              'training_executed': False, 'checked': len(rows), 'circuits': rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Verilog/library/graph/catalog checks passed; no training executed.', flush=True)


if __name__ == '__main__':
    main()
