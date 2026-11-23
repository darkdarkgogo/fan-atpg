"""Discover any test netlists and check native graph/catalog compatibility."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fault_order_rl.testing import (DEFAULT_TEST_DIR,DEFAULT_LIBRARY,DEFAULT_TEST_MANIFEST,discover_test_manifest)
from fault_order_rl.data import load_manifest
from fault_order_rl.environment import load_cpp_fan

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-dir',type=Path,default=DEFAULT_TEST_DIR)
    parser.add_argument('--library',type=Path,default=DEFAULT_LIBRARY)
    parser.add_argument('--output',type=Path,default=ROOT/'validation/reports/test_inputs.json')
    args=parser.parse_args()
    manifest=load_manifest(discover_test_manifest(args.test_dir,args.library,DEFAULT_TEST_MANIFEST))
    native=load_cpp_fan(manifest.module_dir)
    results=[]
    for spec in manifest.circuits:
        print('Checking '+spec.name,flush=True)
        graph=native.circuit_graph(str(spec.netlist_path),str(spec.library_path))
        count=len(graph['gates']); states=len(graph.get('scan',{}).get('state_input_gate_ids',[]))
        del graph
        catalog=native.catalog_stuck_at(str(spec.netlist_path),str(spec.library_path))
        assert sum(row['eqv_fault_num'] for row in catalog['faults'])==catalog['uncollapsed_total']
        row=dict(name=spec.name,netlist=spec.netlist_path.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(spec.netlist_path.read_bytes()).hexdigest(),native_gates=count,
            scan_ffs=states,catalog_rows=len(catalog['faults']),functional_faults=catalog['uncollapsed_total'])
        results.append(row); del catalog
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(circuits=results,training_executed=False),indent=2)+'\n')
        print(json.dumps(row),flush=True)

if __name__=='__main__':main()
