"""Optional frozen real-model native graph inference; never trains."""
import numpy as np
import pytest
import sys
import types
from fault_embedding.fan import lower_native_circuit
from fault_embedding.features import compose_fault_embeddings
from fault_embedding.inference import DEFAULT_CHECKPOINT, infer_gate_embeddings


def _tiny_graph():
    native={'schema':'fan_circuit_graph_v1','gates':[
        {'gate_id':0,'name':'a','kind':'PI','fanins':[]},
        {'gate_id':1,'name':'b','kind':'PI','fanins':[]},
        {'gate_id':2,'name':'z','kind':'AND2','fanins':[0,1]},
        {'gate_id':3,'name':'out','kind':'PO','fanins':[2]}],
        'input_gate_ids':[0,1],'output_gate_ids':[3],
        'input_names':['a','b'],'output_names':['out']}
    return lower_native_circuit(native)


def test_repeated_inference_accepts_active_pyg_generated_propagate(tmp_path,monkeypatch):
    """PyG creates this module in /tmp after the first model construction."""
    pytest.importorskip('torch_geometric')
    graph=_tiny_graph()
    before,_=infer_gate_embeddings(graph)
    layer_class=sys.modules['deepgate.arch.tfmlp'].TFMlpAggr
    module_name='deepgate.arch.tfmlp_TFMlpAggr_propagate'
    module=types.ModuleType(module_name)
    path=tmp_path/(module_name+'_generated.py')
    path.write_text('def propagate(self, *args, **kwargs):\n    return original(self, *args, **kwargs)\n')
    module.__file__=str(path)
    module.original=layer_class.propagate
    exec(compile(path.read_text(),str(path),'exec'),module.__dict__)
    monkeypatch.setitem(sys.modules,module_name,module)
    monkeypatch.setattr(layer_class,'propagate',module.propagate)
    for _ in range(2):
        after,_=infer_gate_embeddings(graph)
        np.testing.assert_array_equal(after['hf'],before['hf'])


def test_generated_looking_foreign_module_still_rejected(tmp_path,monkeypatch):
    pytest.importorskip('torch_geometric')
    graph=_tiny_graph()
    infer_gate_embeddings(graph)
    name='deepgate.arch.tfmlp_TFMlpAggr_edge_updater'
    fake=types.ModuleType(name)
    fake.__file__=str(tmp_path/'foreign.py')
    monkeypatch.setitem(sys.modules,name,fake)
    with pytest.raises(ValueError,match='Another DeepGate module'):
        infer_gate_embeddings(graph)


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
