"""Optional frozen real-model native graph inference; never trains."""
import numpy as np
import pytest
from fault_embedding.fan import lower_native_circuit
from fault_embedding.features import compose_fault_embeddings
from fault_embedding.inference import DEFAULT_CHECKPOINT, infer_gate_embeddings


@pytest.mark.skipif(not DEFAULT_CHECKPOINT.exists(), reason='Official checkpoint has not been downloaded')
def test_official_hf_fault_feature_is_invariant_to_commutative_input_swap():
    pytest.importorskip('torch')
    pytest.importorskip('torch_geometric')
    features = []
    for pins in ([0, 1], [1, 0]):
        native = {'schema': 'fan_circuit_graph_v1', 'gates': [
            {'gate_id': 0, 'name': 'a', 'kind': 'PI', 'fanins': []},
            {'gate_id': 1, 'name': 'b', 'kind': 'PI', 'fanins': []},
            {'gate_id': 2, 'name': 'y', 'kind': 'AND2', 'fanins': pins},
            {'gate_id': 3, 'name': 'po', 'kind': 'PO', 'fanins': [2]}],
            'input_gate_ids': [0, 1], 'output_gate_ids': [3], 'input_names': ['a', 'b'], 'output_names': ['y']}
        graph = lower_native_circuit(native)
        arrays, provenance = infer_gate_embeddings(graph, seed=0)
        assert provenance['is_known_official_checkpoint']
        fault = {'fault_id': 'g2:GI0:sa1', 'io': 'GI', 'sa_value': 1,
                 'gate_function_anchor_node': graph['anchors']['g2'],
                 'connected_function_anchor_node': graph['anchors']['g0']}
        features.append(compose_fault_embeddings(arrays['hf'], [fault]))
    np.testing.assert_array_equal(features[0], features[1])
