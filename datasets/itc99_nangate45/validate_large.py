"""Check fullscan graphs and native target ATPG without starting PPO training."""
import hashlib
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root),str(root/'FAN_ATPG')]
import cpp_fan
from fault_embedding.native_aig import lower_native_circuit, verify_native_equivalence
from fault_embedding.fan import resolve_fan_faults
from validation.independent_sim import read_circuit, evaluate

library=root/'FAN_ATPG/techlib/mod_nangate45.mdt'
results=[]
for c in ('b12','b15','b20','b21','b22'):
    path=root/'FAN_ATPG/netlist'/(c+'_nangate45.v')
    graph=cpp_fan.circuit_graph(str(path),str(library))
    catalog=cpp_fan.catalog_stuck_at(str(path),str(library))
    aig=lower_native_circuit(graph)
    verify_native_equivalence(graph,aig,vectors=32)
    resolve_fan_faults(catalog,graph,aig)
    session=cpp_fan.StuckAtSession(str(path),str(library),dtc_enabled=True,stc_enabled=True)
    rows={r['fault_id']:r for r in catalog['faults']}
    independent=read_circuit(graph)
    detected=0
    # Deterministic targets distributed across state, logic and output cones.
    ids=list(rows)
    targets=list(dict.fromkeys(ids[i*(len(ids)-1)//63] for i in range(64)))
    attempts=0
    for fault_id in targets:
        if fault_id not in session.remaining_fault_ids(): continue
        step=session.step(fault_id)
        attempts+=1
        if not step['generated_pattern']: continue
        pattern=[int(v) for v in step['generated_test_vector']]
        r=rows[fault_id]
        fault=('GO' if r['io'] else 'GI',r['gate_id'],r['input_index'],r['fault_type'])
        assert evaluate(independent,pattern,1)!=evaluate(independent,pattern,1,fault),fault_id
        detected+=1
    stats=dict(circuit=c,netlist=path.relative_to(root).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        native_gates=len(graph['gates']),scan_ffs=len(graph['scan']['state_input_gate_ids']),
        inputs=len(graph['input_names']),outputs=len(graph['output_names']),
        functional_faults=catalog['uncollapsed_total'],catalog_rows=len(catalog['faults']),
        aig_nodes=len(aig['nodes']),aig_equivalence_vectors=32,target_attempts=attempts,
        independently_verified_target_patterns=detected,full_atpg_executed=False,training_executed=False)
    results.append(stats)
    (Path(__file__).parent/'validation_large.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(stats),flush=True)
