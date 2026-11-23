"""Manifest loading and strict embedding/catalog validation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import torch

from fault_embedding.fan import (canonical_catalog, catalog_digest, resolve_fan_faults,
                                 validate_native_graph)
from fault_embedding.inference import OFFICIAL_CHECKPOINT_SHA256, OFFICIAL_SOURCE_SHA256

from .progress import progress


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class CircuitSpec:
    name: str
    netlist_path: Path
    library_path: Path
    embeddings_path: Path
    metadata_path: Path
    graph_path: Path


@dataclass
class CircuitData:
    spec: CircuitSpec
    embeddings: torch.Tensor
    fault_ids: tuple
    eqv_fault_nums: np.ndarray
    artifact_digest: str

    @property
    def name(self):
        return self.spec.name

    @property
    def fault_count(self):
        return len(self.fault_ids)


@dataclass
class TrainingManifest:
    path: Path
    module_dir: Path
    circuits: list
    digest: str


def load_manifest(path):
    path = Path(path).resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read training manifest {}: {}".format(path, exc))
    if not isinstance(raw, dict) or raw.get("version") != 2:
        raise ValueError("training manifest version must be 2 (Verilog+MDT); regenerate old manifests")
    if raw.get("backend") != "FAN" or raw.get("input_format") != "verilog":
        raise ValueError("training manifest requires backend FAN and input_format verilog")
    base = path.parent
    if not isinstance(raw.get("cpp_fan_dir"), str) or not raw["cpp_fan_dir"].strip():
        raise ValueError("training manifest requires cpp_fan_dir")
    module_dir = (base / raw["cpp_fan_dir"]).resolve()
    entries = raw.get("circuits")
    if not isinstance(entries, list) or not entries:
        raise ValueError("training manifest must contain circuits")
    specs = []
    names = set()
    required = {"name", "netlist", "library", "graph", "embeddings", "metadata"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError("each circuit requires exactly name, netlist, library, graph, embeddings, metadata; legacy BENCH keys are unsupported")
        if any(not isinstance(entry[key], str) or not entry[key].strip() for key in required):
            raise ValueError("circuit fields must be nonempty strings")
        name = entry["name"]
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name) or name in names:
            raise ValueError("circuit names must be unique safe file names")
        names.add(name)
        if Path(entry["netlist"]).suffix.lower() not in (".v", ".sv"):
            raise ValueError("FAN netlist must be structural Verilog (.v or .sv)")
        if Path(entry["library"]).suffix.lower() != ".mdt":
            raise ValueError("FAN technology library must be .mdt")
        specs.append(CircuitSpec(name, (base / entry["netlist"]).resolve(),
                                 (base / entry["library"]).resolve(),
                                 (base / entry["embeddings"]).resolve(),
                                 (base / entry["metadata"]).resolve(),
                                 (base / entry["graph"]).resolve()))
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return TrainingManifest(path, module_dir, specs, hashlib.sha256(canonical).hexdigest())


def load_circuit_data(spec, catalog, native_circuit=None):
    if spec.netlist_path.suffix.lower() not in (".v", ".sv"):
        raise ValueError("FAN requires a structural Verilog netlist (.v or .sv)")
    if spec.library_path.suffix.lower() != ".mdt":
        raise ValueError("FAN requires a technology library (.mdt)")
    paths = [spec.netlist_path, spec.library_path, spec.embeddings_path,
             spec.metadata_path, spec.graph_path]
    for path in paths:
        if not path.is_file():
            raise ValueError("missing circuit artifact: {}".format(path))

    try:
        metadata = json.loads(spec.metadata_path.read_text(encoding="utf-8"))
        if metadata.get("schema") != "fan_verilog_embeddings_v1":
            raise ValueError("requires FAN Verilog embedding schema; regenerate legacy artifacts")
        with np.load(str(spec.embeddings_path), allow_pickle=False) as arrays:
            embeddings = np.asarray(arrays["embeddings"], dtype=np.float32)
            fault_ids = tuple(str(value) for value in arrays["fault_ids"].tolist())
            eqv_fault_nums = np.asarray(arrays["eqv_fault_nums"], dtype=np.int64)
            graph_sha256 = str(arrays["graph_sha256"].item())
            embedding_backend = str(arrays["backend"].item())
            embedding_catalog_sha256 = str(arrays["catalog_sha256"].item())
            provenance = json.loads(str(arrays["provenance_json"].item()))
            embedding_hashes = {
                key: str(arrays[key].item())
                for key in ("source_sha256", "library_sha256", "native_circuit_sha256", "graph_sha256")
                if key in arrays
            }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("cannot load embeddings for {}: {}".format(spec.name, exc))

    if embeddings.ndim != 2 or embeddings.shape[1] != 257:
        raise ValueError("{} embeddings must have shape [N, 257]".format(spec.name))
    if embeddings.shape[0] == 0 or not np.isfinite(embeddings).all():
        raise ValueError("{} embeddings are empty or non-finite".format(spec.name))
    if len(fault_ids) != embeddings.shape[0] or len(set(fault_ids)) != len(fault_ids):
        raise ValueError("{} embedding fault IDs are missing or duplicated".format(spec.name))
    if eqv_fault_nums.shape != (embeddings.shape[0],) or np.any(eqv_fault_nums <= 0):
        raise ValueError("{} equivalence counts are invalid".format(spec.name))
    if any(identifier.startswith("__smartatpg_bin_") for identifier in fault_ids):
        raise ValueError("{} contains helper-derived fault IDs".format(spec.name))

    metadata_ids = tuple(str(item["fault_id"]) for item in metadata.get("faults", []))
    metadata_eqv = np.asarray(
        [int(item["eqv_fault_num"]) for item in metadata.get("faults", [])],
        dtype=np.int64,
    )
    catalog_faults = list(catalog.get("faults", []))
    catalog_ids = tuple(str(item["fault_id"]) for item in catalog_faults)
    if fault_ids != metadata_ids or fault_ids != catalog_ids:
        raise ValueError("{} fault IDs do not match metadata and FAN catalog".format(spec.name))
    catalog_eqv = np.asarray(
        [int(item["eqv_fault_num"]) for item in catalog_faults], dtype=np.int64
    )
    if not np.array_equal(eqv_fault_nums, catalog_eqv):
        raise ValueError("{} equivalence counts do not match FAN".format(spec.name))
    if not np.array_equal(metadata_eqv, catalog_eqv):
        raise ValueError("{} metadata equivalence counts do not match FAN".format(spec.name))
    if int(catalog.get("uncollapsed_total", -1)) != int(eqv_fault_nums.sum()):
        raise ValueError("{} uncollapsed fault total does not match".format(spec.name))
    if metadata.get("status") != "embeddings_exported":
        raise ValueError("{} metadata is not an embedding export".format(spec.name))
    if metadata.get("graph_sha256") != graph_sha256:
        raise ValueError("{} graph provenance does not match".format(spec.name))

    if metadata.get("backend") != "FAN" or embedding_backend != "FAN":
        raise ValueError("{} embeddings must identify the FAN backend".format(spec.name))
    try:
        current_catalog = canonical_catalog(catalog)
        current_digest = catalog_digest(catalog)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid FAN catalog attributes") from exc
    if (metadata.get("native_catalog") != current_catalog
            or metadata.get("catalog_sha256") != current_digest
            or embedding_catalog_sha256 != current_digest):
        raise ValueError("{} FAN catalog provenance does not match".format(spec.name))
    try:
        graph = json.loads(spec.graph_path.read_text(encoding="utf-8"))
        validate_native_graph(graph)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("{} invalid native circuit graph: {}".format(spec.name, exc)) from exc
    if native_circuit is not None and graph["native_circuit"] != native_circuit:
        raise ValueError("{} native circuit differs from current FAN input".format(spec.name))
    expected_hashes = {"source_sha256": _sha256(spec.netlist_path),
                       "library_sha256": _sha256(spec.library_path),
                       "native_circuit_sha256": graph["native_circuit_sha256"],
                       "graph_sha256": graph["graph_sha256"]}
    for key, value in expected_hashes.items():
        if metadata.get(key) != value or embedding_hashes.get(key) != value:
            raise ValueError("{} {} provenance does not match".format(spec.name, key))
    if metadata.get("fault_count") != len(fault_ids):
        raise ValueError("{} metadata fault count does not match".format(spec.name))
    if metadata.get("uncollapsed_total") != int(eqv_fault_nums.sum()):
        raise ValueError("{} metadata uncollapsed total does not match".format(spec.name))
    if metadata["faults"] != resolve_fan_faults(catalog, graph["native_circuit"], graph):
        raise ValueError("{} FAN fault anchors do not match native circuit".format(spec.name))
    if provenance != metadata.get("provenance") or (
        provenance.get("checkpoint_sha256") != OFFICIAL_CHECKPOINT_SHA256
        or provenance.get("source_sha256") != OFFICIAL_SOURCE_SHA256
        or provenance.get("backend") != "official-python-deepgate"
        or provenance.get("is_known_official_checkpoint") is not True
    ):
        raise ValueError("{} pretrained embedding provenance does not match".format(spec.name))

    artifact_paths = paths
    artifact_digest = hashlib.sha256(
        (spec.name + "".join(_sha256(path) for path in artifact_paths)).encode("utf-8")
    ).hexdigest()
    tensor = torch.from_numpy(np.array(embeddings, copy=True))
    return CircuitData(spec, tensor, fault_ids, eqv_fault_nums, artifact_digest)


def load_all_circuits(manifest, environment):
    # C++ input historically terminates on missing files. Preflight the entire
    # dataset before entering the binding, even for catalog-only validation.
    for spec in manifest.circuits:
        for path in (spec.netlist_path, spec.library_path, spec.embeddings_path,
                     spec.metadata_path, spec.graph_path):
            if not path.is_file():
                raise ValueError("missing circuit artifact: {}".format(path))
    circuits = []
    for spec in manifest.circuits:
        started = time.perf_counter()
        progress("LOAD", "catalog start", circuit=spec.name)
        try:
            catalog = environment.catalog(spec.netlist_path, spec.library_path)
        except Exception as exc:
            progress(
                "LOAD", "catalog error", circuit=spec.name,
                error_type=type(exc).__name__, error=str(exc),
                elapsed_s="{:.3f}".format(time.perf_counter() - started),
            )
            raise
        progress(
            "LOAD", "catalog done", circuit=spec.name,
            elapsed_s="{:.3f}".format(time.perf_counter() - started),
        )

        started = time.perf_counter()
        progress("LOAD", "validation start", circuit=spec.name)
        try:
            native = environment.circuit_graph(spec.netlist_path, spec.library_path)
            circuit = load_circuit_data(spec, catalog, native)
        except Exception as exc:
            progress(
                "LOAD", "validation error", circuit=spec.name,
                error_type=type(exc).__name__, error=str(exc),
                elapsed_s="{:.3f}".format(time.perf_counter() - started),
            )
            raise
        progress(
            "LOAD", "validation done", circuit=spec.name,
            elapsed_s="{:.3f}".format(time.perf_counter() - started),
        )
        circuits.append(circuit)
    return circuits
