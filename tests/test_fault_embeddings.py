"""Strict functional feature composition, independent of model inference."""
import numpy as np
import pytest
from fault_embedding.features import compose_fault_embeddings, compose_original_fault_embeddings


def fault(identifier='g2:GI0:sa1', io='GI', receiver=2, source=0, sa=1):
    return {'fault_id': identifier, 'io': io, 'gate_function_anchor_node': receiver,
            'connected_function_anchor_node': source, 'sa_value': sa}


def test_features_use_receiver_source_and_polarity():
    hf = np.arange(3 * 128, dtype=np.float32).reshape(3, 128)
    rows = [fault(), fault('g2:GI1:sa0', source=1, sa=0), fault('g2:GO:sa1', io='GO', source=2)]
    result = compose_original_fault_embeddings(hf, rows)
    assert result.shape == (3, 257)
    np.testing.assert_array_equal(result[0, :128], hf[2])
    np.testing.assert_array_equal(result[0, 128:256], hf[0])
    np.testing.assert_array_equal(result[1, 128:256], hf[1])
    np.testing.assert_array_equal(result[2, :128], result[2, 128:256])
    assert result[:, -1].tolist() == [1, 0, 1]


def test_pin_permutation_preserves_same_function_feature():
    hf = np.arange(3 * 128, dtype=np.float32).reshape(3, 128)
    first = compose_original_fault_embeddings(hf, [fault('g2:GI0:sa1')])
    second = compose_original_fault_embeddings(hf, [fault('g2:GI1:sa1')])
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize('row,reason', [
    (fault(receiver=-1), 'anchor'), (fault(source=3), 'anchor'),
    (fault(io='GO'), 'GO must duplicate'), (fault(io='bad'), 'I/O'), (fault(sa=2), 'polarity')])
def test_invalid_faults_rejected(row, reason):
    with pytest.raises(ValueError, match=reason):
        compose_fault_embeddings(np.ones((3, 128), np.float32), [row])


def test_invalid_features_rejected():
    with pytest.raises(ValueError, match='non-finite'):
        compose_fault_embeddings(np.array([[np.nan]], np.float32), [])
    with pytest.raises(ValueError, match='Duplicate'):
        compose_fault_embeddings(np.ones((3, 128), np.float32), [fault(), fault()])
    with pytest.raises(ValueError, match='257'):
        compose_original_fault_embeddings(np.ones((3, 4), np.float32), [fault()])
    assert compose_fault_embeddings(np.ones((3, 4), np.float32), []).shape == (0, 9)
