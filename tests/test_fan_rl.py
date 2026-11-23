"""FAN identity, migration and artifact boundary regression tests."""
import copy
import json
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from fault_embedding.fan import canonical_catalog, catalog_digest, resolve_fan_faults, lower_native_circuit
from fault_embedding.inference import OFFICIAL_CHECKPOINT_SHA256, OFFICIAL_SOURCE_SHA256
from fault_order_rl.checkpoint import load_checkpoint, save_checkpoint
from fault_order_rl.data import CircuitSpec, _sha256, load_circuit_data, load_manifest
from fault_order_rl.environment import PROTOCOL_CONFIG, load_cpp_fan, FanEnvironment
from fault_order_rl.trainer import TrainConfig, _check_split_independence


def test_loader_imports_only_fan(monkeypatch):
    requested = []
    fake = SimpleNamespace(catalog_stuck_at=lambda: None, circuit_graph=lambda: None,
                           run_stuck_at_ordered=lambda: None, StuckAtSession=object)
    def import_module(name):
        requested.append(name)
        return fake
    monkeypatch.setattr("fault_order_rl.environment.importlib.import_module", import_module)
    assert load_cpp_fan() is fake
    assert requested == ["cpp_fan"]
    assert PROTOCOL_CONFIG["backend"] == "FAN"
    assert PROTOCOL_CONFIG["protocol_version"] == "fan_verilog_fullscan_v3"


def test_rounds_are_positive_and_default_one():
    assert TrainConfig().rounds == 1
    for rounds in (1, 2, 8):
        TrainConfig(rounds=rounds).validate()
    for rounds in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="positive integer"):
            TrainConfig(rounds=rounds).validate()


def test_checkpoint_requires_explicit_fan_identity(tmp_path):
    path = tmp_path / "model.pt"
    for version in (5, 6):
        save_checkpoint(path, {"version": version})
        with pytest.raises(ValueError, match="PODEM checkpoints"):
            load_checkpoint(path)
    save_checkpoint(path, {"version": 7, "solver_protocol": PROTOCOL_CONFIG})
    with pytest.raises(ValueError, match="BENCH schema 7"):
        load_checkpoint(path)
    save_checkpoint(path, {"version": 8, "solver_protocol": {"backend":"FAN","protocol_version":"fan_verilog_v2"}})
    with pytest.raises(ValueError, match="unsupported"):
        load_checkpoint(path)
    save_checkpoint(path, {"version": 9})
    with pytest.raises(ValueError, match="not a FAN"):
        load_checkpoint(path)
    save_checkpoint(path, {"version": 9, "solver_protocol": PROTOCOL_CONFIG})
    assert load_checkpoint(path)["version"] == 9


def _manifest_entry():
    return {"name": "tiny", "netlist": "a.v", "library": "cells.mdt",
            "graph": "a.graph.json", "embeddings": "a.npz", "metadata": "a.json"}


def test_manifest_requires_verilog_identity_and_directory(tmp_path):
    path = tmp_path / "train.json"
    raw = {"version": 2, "backend": "FAN", "input_format": "verilog",
           "cpp_fan_dir": "native", "circuits": [_manifest_entry()]}
    path.write_text(json.dumps(raw))
    manifest = load_manifest(path)
    assert manifest.module_dir == (tmp_path / "native").resolve()
    assert manifest.circuits[0].library_path == tmp_path / "cells.mdt"
    for key, bad in (("version", 1), ("backend", "PODEM"), ("input_format", "bench"),
                     ("cpp_fan_dir", "")):
        changed = dict(raw, **{key: bad})
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            load_manifest(path)


@pytest.mark.parametrize("key", ["bench", "faultmap", "aig_bench", "aigmap"])
def test_manifest_rejects_legacy_entry_keys(tmp_path, key):
    entry = dict(_manifest_entry(), **{key: "legacy.bench"})
    path = tmp_path / "train.json"
    path.write_text(json.dumps({"version": 2, "backend": "FAN", "input_format": "verilog",
                               "cpp_fan_dir": ".", "circuits": [entry]}))
    with pytest.raises(ValueError, match="legacy BENCH"):
        load_manifest(path)


@pytest.fixture
def fan_artifacts(tmp_path):
    netlist = tmp_path / "tiny.v"
    netlist.write_text("module tiny(input a,b,output y); AND2 u(y,a,b); endmodule\n")
    library = tmp_path / "cells.mdt"
    library.write_text("unit-test library provenance")
    native = {"schema": "fan_circuit_graph_v1", "gates": [
        {"gate_id": 0, "name": "a", "kind": "PI", "fanins": []},
        {"gate_id": 1, "name": "b", "kind": "PI", "fanins": []},
        {"gate_id": 2, "name": "u", "kind": "AND2", "fanins": [0, 1]},
        {"gate_id": 3, "name": "y", "kind": "PO", "fanins": [2]}],
        "input_gate_ids": [0, 1], "output_gate_ids": [3],
        "input_names": ["a", "b"], "output_names": ["y"]}
    graph = lower_native_circuit(native)
    graph_path = tmp_path / "tiny.graph.json"
    graph_path.write_text(json.dumps(graph))
    catalog = {"faults": [{"fault_id": "g2:GO:sa0", "gate_id": 2, "node_name": "g2",
        "input_wire_name": "-", "io": 1, "input_index": -1,
        "input_occurrence": -1, "fault_type": 0, "eqv_fault_num": 1}],
        "uncollapsed_total": 1}
    provenance = {"checkpoint_sha256": OFFICIAL_CHECKPOINT_SHA256,
        "source_sha256": OFFICIAL_SOURCE_SHA256, "backend": "official-python-deepgate",
        "is_known_official_checkpoint": True}
    hashes = {"source_sha256": _sha256(netlist), "library_sha256": _sha256(library),
              "native_circuit_sha256": graph["native_circuit_sha256"]}
    metadata = {"schema": "fan_verilog_embeddings_v1", "backend": "FAN",
        "status": "embeddings_exported", "fault_count": 1, "uncollapsed_total": 1,
        "graph_sha256": graph["graph_sha256"], "provenance": provenance,
        "native_catalog": canonical_catalog(catalog), "catalog_sha256": catalog_digest(catalog),
        "faults": resolve_fan_faults(catalog, native, graph), **hashes}
    meta = tmp_path / "tiny.json"
    meta.write_text(json.dumps(metadata))
    embeddings = tmp_path / "tiny.npz"
    # Unit fixture only; production exporter requires the actual official encoder.
    np.savez(embeddings, embeddings=np.zeros((1, 257), dtype=np.float32),
        fault_ids=np.array(["g2:GO:sa0"]), eqv_fault_nums=np.array([1]),
        graph_sha256=graph["graph_sha256"], backend="FAN",
        catalog_sha256=catalog_digest(catalog), provenance_json=json.dumps(provenance), **hashes)
    return CircuitSpec("tiny", netlist, library, embeddings, meta, graph_path), catalog, metadata


def test_fan_catalog_and_original_anchor_alignment(fan_artifacts):
    spec, catalog, metadata = fan_artifacts
    assert load_circuit_data(spec, catalog).embeddings.shape == (1, 257)
    changed = copy.deepcopy(catalog)
    changed["faults"][0]["fault_type"] = 1
    with pytest.raises(ValueError, match="catalog provenance"):
        load_circuit_data(spec, changed)
    metadata["faults"][0]["gate_function_anchor_node"] += 1
    spec.metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="fault anchors"):
        load_circuit_data(spec, catalog)




@pytest.mark.parametrize("artifact", ["netlist_path", "library_path"])
def test_source_and_library_hashes_are_enforced(fan_artifacts, artifact):
    spec, catalog, _ = fan_artifacts
    getattr(spec, artifact).write_text("changed")
    with pytest.raises(ValueError, match="provenance does not match"):
        load_circuit_data(spec, catalog)


def test_current_native_graph_is_enforced(fan_artifacts):
    spec, catalog, _ = fan_artifacts
    with pytest.raises(ValueError, match="differs from current FAN input"):
        load_circuit_data(spec, catalog, {"schema": "wrong"})



@pytest.mark.parametrize("netlist,library", [("tiny.bench", "cells.mdt"),
    ("tiny.v", None), ("tiny.v", ""), ("tiny.v", "cells.bench")])
def test_environment_rejects_legacy_or_missing_library(netlist, library):
    with pytest.raises(ValueError, match="requires"):
        FanEnvironment._check_files(netlist, library)


def test_split_allows_shared_library_but_rejects_copied_netlist(tmp_path):
    def circuit(name):
        netlist = tmp_path / (name + ".v")
        netlist.write_text(name)
        spec = CircuitSpec(name, netlist, tmp_path / "shared.mdt",
                           tmp_path / (name + ".npz"), tmp_path / (name + ".json"),
                           tmp_path / (name + ".graph.json"))
        return SimpleNamespace(spec=spec, artifact_digest=name)
    training, validation = circuit("train"), circuit("validation")
    _check_split_independence([training], [validation])
    validation.spec.netlist_path.write_bytes(training.spec.netlist_path.read_bytes())
    with pytest.raises(ValueError, match="independent"):
        _check_split_independence([training], [validation])
