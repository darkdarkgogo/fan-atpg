import pytest
from validation.independent_sim import coverage


def and_graph():
    return {'schema':'fan_circuit_graph_v1','input_gate_ids':[0,1],'output_gate_ids':[3],
            'input_names':['a','b'],'output_names':['z'],'gates':[
                {'gate_id':0,'name':'a','kind':'PI','fanins':[]},
                {'gate_id':1,'name':'b','kind':'PI','fanins':[]},
                {'gate_id':2,'name':'and','kind':'AND2','fanins':[0,1]},
                {'gate_id':3,'name':'z','kind':'PO','fanins':[2]}]}


def test_and_full_vectors_detect_all_faults():
    graph=and_graph()
    result=coverage(graph,['00','01','10','11'])
    assert result['total']==12 and result['detected']==12
    assert coverage(graph,['11'])['detected']==6


def test_reordered_vectors_and_reconvergence():
    graph=and_graph()
    graph['gates'][2]['kind']='NAND2'
    graph['gates'].insert(3,{'gate_id':4,'name':'xor','kind':'XOR2','fanins':[2,0]})
    graph['gates'][-1]['fanins']=[4]
    assert coverage(graph,['00','01','10'],['a','b'])['detected']==coverage(graph,['00','10','01'],['b','a'])['detected']
    with pytest.raises(ValueError,match='fully specified'):
        coverage(graph,['1X'])


def test_bench_input_not_supported(tmp_path):
    source=tmp_path/'old.bench'; source.write_text('INPUT(a)\nOUTPUT(a)\n')
    with pytest.raises(ValueError,match='exported native'):
        coverage(source,['0','1'])
