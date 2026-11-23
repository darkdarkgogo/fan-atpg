"""Compose swap-invariant functional embeddings for collapsed faults."""

import numpy as np
import hashlib
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compose_original_fault_embeddings(gate_hf, fault_records):
    features = compose_fault_embeddings(gate_hf, fault_records)
    if features.shape != (len(fault_records), 257):
        raise ValueError("Original fault embeddings must have shape [fault_count, 257]")
    return features


def compose_fault_embeddings(function_embeddings, faults):
    functions = np.asarray(function_embeddings)
    if (functions.ndim != 2 or functions.shape[1] < 1
            or not np.issubdtype(functions.dtype, np.floating)):
        raise ValueError("Functional embeddings must be a floating point [nodes, dimensions] matrix")
    if not np.isfinite(functions).all():
        raise ValueError("Functional embeddings contain non-finite values")
    gate_anchors, connected_anchors, polarities = [], [], []
    ids = set()
    for fault in faults:
        if fault["fault_id"] in ids:
            raise ValueError("Duplicate fault ID")
        ids.add(fault["fault_id"])
        gate_anchor = fault["gate_function_anchor_node"]
        connected_anchor = fault["connected_function_anchor_node"]
        sa = fault["sa_value"]
        for label, anchor in (("gate", gate_anchor), ("connected", connected_anchor)):
            if not isinstance(anchor, int) or not 0 <= anchor < len(functions):
                raise ValueError(f"Invalid {label} functional anchor for {fault['fault_id']}")
        if fault["io"] == "GO" and connected_anchor != gate_anchor:
            raise ValueError(f"GO must duplicate the gate functional embedding: {fault['fault_id']}")
        if fault["io"] not in ("GO", "GI"):
            raise ValueError(f"Invalid fault I/O type for {fault['fault_id']}")
        if sa not in (0, 1):
            raise ValueError("Fault polarity must be SA0=0 or SA1=1")
        gate_anchors.append(gate_anchor)
        connected_anchors.append(connected_anchor)
        polarities.append(sa)
    gate_selected = functions[np.asarray(gate_anchors, dtype=np.int64)].astype(np.float32)
    connected_selected = functions[np.asarray(connected_anchors, dtype=np.int64)].astype(np.float32)
    polarity = np.asarray(polarities, dtype=np.float32).reshape(-1, 1)
    result = np.concatenate([gate_selected, connected_selected, polarity], axis=1)
    if not np.isfinite(result).all():
        raise ValueError("Fault embeddings overflow float32")
    return result
