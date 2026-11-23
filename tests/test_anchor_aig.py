"""Native AIG validation and strict failure paths."""
import copy
import pytest
from fault_embedding.native_aig import (lower_native_circuit, validate_native_graph,
    verify_native_equivalence, native_circuit_digest)


def circuit():
    return {'schema': 'fan_circuit_graph_v1', 'gates': [
        {'gate_id': 0, 'name': 'a', 'kind': 'PI', 'fanins': []},
        {'gate_id': 1, 'name': 'x', 'kind': 'INV', 'fanins': [0]},
        {'gate_id': 2, 'name': 'o', 'kind': 'PO', 'fanins': [1]}],
        'input_gate_ids': [0], 'output_gate_ids': [2], 'input_names': ['a'], 'output_names': ['o']}


def test_snapshot_is_independent_and_hash_covers_names():
    native = circuit()
    graph = lower_native_circuit(native)
    digest = native_circuit_digest(native)
    native['gates'][1]['name'] = 'changed'
    assert graph['native_circuit']['gates'][1]['name'] == 'x'
    assert native_circuit_digest(native) != digest
    assert validate_native_graph(graph)['gates'][1]['name'] == 'x'


def test_non_topological_native_ids_are_lowered_topologically():
    native = circuit()
    native['gates'][1].update(kind='PO', fanins=[2])
    native['gates'][2].update(kind='INV', fanins=[0])
    native['output_gate_ids'] = [1]
    graph = lower_native_circuit(native)
    verify_native_equivalence(native, graph)
    assert graph['anchors']['g2'] < graph['anchors']['g1']


@pytest.mark.parametrize('change,message', [
    (lambda c: c['gates'][1].update(fanins=[3]), 'fanin ID'),
    (lambda c: c['gates'][1].update(fanins=[2]), 'cycle'),
    (lambda c: c['gates'][1].update(gate_id=9), 'contiguous'),
    (lambda c: c.update(input_gate_ids=[]), 'boundary ports'),
    (lambda c: c['gates'][1].update(kind='AND4'), 'arity')])
def test_invalid_native_structure_rejected(change, message):
    native = circuit()
    change(native)
    with pytest.raises(ValueError, match=message):
        lower_native_circuit(native)


def test_scalar_checker_detects_changed_anchor():
    native = circuit()
    graph = lower_native_circuit(native)
    graph['anchors']['g1'] = graph['anchors']['g0']
    with pytest.raises(ValueError, match='mismatch at g1'):
        verify_native_equivalence(native, graph)


def test_constants_without_real_pi_rejected():
    native = {'schema': 'fan_circuit_graph_v1', 'gates': [
        {'gate_id': 0, 'name': 'zero', 'kind': 'TIE0', 'fanins': []},
        {'gate_id': 1, 'name': 'o', 'kind': 'PO', 'fanins': [0]}],
        'input_gate_ids': [], 'output_gate_ids': [1], 'input_names': [], 'output_names': ['o']}
    with pytest.raises(ValueError, match='real PI'):
        lower_native_circuit(native)
