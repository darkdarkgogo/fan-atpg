"""Native FAN identities, pin occurrences, and every-gate AIG truth tables."""
import copy
import itertools
import numpy as np
import pytest
from fault_embedding.features import compose_original_fault_embeddings
from fault_embedding.fan import (canonical_catalog, catalog_digest, lower_native_circuit,
    resolve_fan_faults, validate_native_graph, verify_native_equivalence)


def fixture(kind='AND2', pins=None):
    pins = [0, 1] if pins is None else pins
    return {'schema': 'fan_circuit_graph_v1', 'gates': [
        {'gate_id': 0, 'name': 'a', 'kind': 'PI', 'fanins': []},
        {'gate_id': 1, 'name': 'b', 'kind': 'PI', 'fanins': []},
        {'gate_id': 2, 'name': 'c', 'kind': 'PI', 'fanins': []},
        {'gate_id': 3, 'name': 'd', 'kind': 'PI', 'fanins': []},
        {'gate_id': 4, 'name': 'y', 'kind': kind, 'fanins': pins},
        {'gate_id': 5, 'name': 'y_po', 'kind': 'PO', 'fanins': [4]}],
        'input_gate_ids': [0, 1, 2, 3], 'output_gate_ids': [5],
        'input_names': ['a', 'b', 'c', 'd'], 'output_names': ['y']}


def row(gate, pin, wire, sa, occurrence=0):
    return {'gate_id': gate, 'fault_id': 'g' + str(gate) + (':GO' if pin < 0 else ':GI' + str(pin)) + ':sa' + str(sa),
        'node_name': 'g' + str(gate), 'input_wire_name': '-' if pin < 0 else 'g' + str(wire),
        'io': int(pin < 0), 'input_index': pin, 'input_occurrence': -1 if pin < 0 else occurrence,
        'fault_type': sa, 'eqv_fault_num': 1}


@pytest.mark.parametrize('kind,pins', [(family + str(arity), list(range(arity)))
    for family in ('AND', 'NAND', 'OR', 'NOR', 'XOR', 'XNOR')
    for arity in ((2, 3) if family in ('XOR', 'XNOR') else (2, 3, 4))]
    + [('INV', [0]), ('BUF', [0]), ('TIE0', []), ('TIE1', [])])
def test_all_native_gate_truth_tables(kind, pins):
    native = fixture(kind, pins)
    graph = lower_native_circuit(native)
    verify_native_equivalence(native, graph)
    assert validate_native_graph(graph) == native
    assert len(set(graph['anchors'].values())) == len(native['gates'])
    assert {n['kind'] for n in graph['nodes']} <= {'INPUT', 'AND', 'NOT'}
    assert graph == lower_native_circuit(copy.deepcopy(native))


def test_native_gate_fault_mapping_and_po_receiver():
    native = fixture()
    graph = lower_native_circuit(native)
    catalog = {'faults': [row(4, 0, 0, 0), row(4, 1, 1, 1), row(0, -1, None, 0), row(5, 0, 4, 1)],
               'uncollapsed_total': 4}
    faults = resolve_fan_faults(catalog, native, graph)
    hf = np.arange(len(graph['nodes']) * 128, dtype=np.float32).reshape(-1, 128)
    features = compose_original_fault_embeddings(hf, faults)
    assert features.shape == (4, 257)
    np.testing.assert_array_equal(features[0, 128:256], hf[graph['anchors']['g0']])
    np.testing.assert_array_equal(features[2, :128], features[2, 128:256])
    assert faults[3]['gate_function_anchor_node'] != graph['anchors']['g4']
    assert features[:, -1].tolist() == [0, 1, 0, 1]


def test_duplicate_pin_occurrences_preserved():
    native = fixture(pins=[0, 0])
    graph = lower_native_circuit(native)
    catalog = {'faults': [row(4, 0, 0, 0), row(4, 1, 0, 1, 1)], 'uncollapsed_total': 2}
    assert [f['input_occurrence'] for f in resolve_fan_faults(catalog, native, graph)] == [0, 1]
    catalog['faults'][1]['input_occurrence'] = 0
    with pytest.raises(ValueError, match='occurrence mismatch'):
        resolve_fan_faults(catalog, native, graph)


def test_catalog_digest_covers_gate_and_pin():
    catalog = {'faults': [row(4, 0, 0, 0)], 'uncollapsed_total': 1, 'backend': 'FAN'}
    digest = catalog_digest(catalog)
    assert 'backend' not in canonical_catalog(catalog)
    catalog['faults'][0]['gate_id'] = 5
    assert catalog_digest(catalog) != digest


def test_changed_graph_rejected():
    graph = lower_native_circuit(fixture())
    graph['anchors']['g4'] = graph['anchors']['g0']
    with pytest.raises(ValueError, match='deterministic'):
        validate_native_graph(graph)


@pytest.mark.parametrize('kind', ['PPI', 'PPO', 'DFF', 'MUX', 'TIEX', 'TIEZ'])
def test_unsupported_native_kinds_rejected(kind):
    with pytest.raises(ValueError, match='Unsupported native gate'):
        lower_native_circuit(fixture(kind, []))


def test_legacy_graph_rejected():
    with pytest.raises(ValueError, match='schema'):
        validate_native_graph({'schema': 'fault_embedding_graph_v1'})
