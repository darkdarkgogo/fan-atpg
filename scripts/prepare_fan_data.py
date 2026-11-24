"""Export frozen pinned DeepGate2 features from FAN Verilog+MDT native circuits."""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fault_embedding.features import compose_original_fault_embeddings, sha256
from fault_embedding.fan import (SCHEMA, canonical_catalog, catalog_digest, resolve_fan_faults,
    lower_native_circuit, native_circuit_digest, verify_native_equivalence)
from fault_embedding.inference import DEFAULT_CHECKPOINT, DEFAULT_SOURCE, infer_gate_embeddings


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def export(spec, catalog, native_circuit, seed=0, device="auto", threads=None):
    target, stem = spec.embeddings_path.parent, spec.netlist_path.stem
    expected = {'graph': target / (stem + '.graph.json'), 'meta': target / (stem + '.faults.json'),
                'emb': target / (stem + '.fault_embeddings.npz'), 'gates': target / (stem + '.gates.npz')}
    if (spec.graph_path != expected['graph'] or spec.metadata_path != expected['meta']
            or spec.embeddings_path != expected['emb']):
        raise ValueError('FAN manifest artifacts must share directory and Verilog stem')
    if any(p.exists() for p in expected.values()):
        from fault_order_rl.data import load_circuit_data
        load_circuit_data(spec, catalog, native_circuit)
        print('Validated existing FAN export: ' + spec.name, flush=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.' + target.name + '.', dir=target.parent))
    paths = {key: temporary / path.name for key, path in expected.items()}
    try:
        graph = lower_native_circuit(native_circuit)
        verify_native_equivalence(native_circuit, graph)
        write_json(paths['graph'], graph)
        faults = resolve_fan_faults(catalog, native_circuit, graph)
        arrays, provenance = infer_gate_embeddings(
            graph, DEFAULT_CHECKPOINT, DEFAULT_SOURCE, seed, device=device, threads=threads)
        features = compose_original_fault_embeddings(arrays['hf'], faults)
        layout = {'gate_feature': 'hf', 'gate_dimension': 128, 'fault_dimension': 257,
                  'columns': ['gate_hf', 'connected_hf', 'sa_value'],
                  'GO_rule': 'both vectors use original driver anchor',
                  'GI_rule': 'receiver anchor then original input wire anchor'}
        hashes = {'source_sha256': sha256(spec.netlist_path), 'library_sha256': sha256(spec.library_path),
                  'catalog_sha256': catalog_digest(catalog), 'native_circuit_sha256': native_circuit_digest(native_circuit),
                  'graph_sha256': graph['graph_sha256']}
        metadata = dict(hashes, schema=SCHEMA, backend='FAN', status='embeddings_exported',
                        source=str(spec.netlist_path), library=str(spec.library_path), graph=str(expected['graph']),
                        fault_count=len(faults), uncollapsed_total=int(catalog['uncollapsed_total']),
                        native_catalog=canonical_catalog(catalog), faults=faults, provenance=provenance, feature_layout=layout)
        write_json(paths['meta'], metadata)
        common = {key: np.asarray(value) for key, value in hashes.items()}
        common.update(backend=np.asarray('FAN'), schema=np.asarray(SCHEMA),
                      provenance_json=np.asarray(json.dumps(provenance, sort_keys=True)))
        np.savez_compressed(str(paths['gates']), hf=arrays['hf'], hs=arrays['hs'], **common)
        np.savez_compressed(str(paths['emb']), embeddings=features,
            fault_ids=np.asarray([f['fault_id'] for f in faults], dtype=str),
            eqv_fault_nums=np.asarray([f['eqv_fault_num'] for f in faults], dtype=np.int64),
            gate_function_anchor_nodes=np.asarray([f['gate_function_anchor_node'] for f in faults], dtype=np.int64),
            connected_function_anchor_nodes=np.asarray([f['connected_function_anchor_node'] for f in faults], dtype=np.int64),
            sa_values=features[:, -1].astype(np.int8),
            feature_layout_json=np.asarray(json.dumps(layout, sort_keys=True)), **common)
        # Dedicated per-circuit directories make the publication atomic.
        if target.exists():
            if any(target.iterdir()):
                raise ValueError('Refusing to replace nonempty artifact directory: ' + str(target))
            target.rmdir()
        os.replace(str(temporary), str(target))
    except BaseException:
        shutil.rmtree(str(temporary), ignore_errors=True)
        raise
    print('Exported FAN {}: {} faults x 257'.format(spec.name, len(faults)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--threads', type=int)
    args = parser.parse_args()
    from fault_order_rl.runtime import configure_runtime
    configure_runtime(args.device, args.threads)
    from fault_order_rl.data import load_manifest, load_circuit_data
    manifest = load_manifest(args.manifest)
    sys.path.insert(0, str(manifest.module_dir))
    native = importlib.import_module('cpp_fan')
    for spec in manifest.circuits:
        catalog = dict(native.catalog_stuck_at(str(spec.netlist_path), str(spec.library_path)))
        circuit = dict(native.circuit_graph(str(spec.netlist_path), str(spec.library_path)))
        export(spec, catalog, circuit, args.seed, device=args.device, threads=args.threads)
        load_circuit_data(spec, catalog, circuit)


if __name__ == '__main__':
    main()
