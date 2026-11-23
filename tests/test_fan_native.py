"""Original Verilog frontend, native ATPG and physical fault simulation checks."""
import itertools
from pathlib import Path
import random
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'FAN_ATPG'))
cpp_fan = pytest.importorskip('cpp_fan')
from validation.independent_sim import coverage
ROOT = Path(__file__).resolve().parents[1]
LIB = str(ROOT / 'datasets/verilog/fan_primitives.mdt')

def write_verilog(tmp_path, inputs, outputs, gates):
    path=tmp_path / '电路.v'
    signals=[name for name,_,_ in gates]
    text=['module top('+','.join(inputs+outputs)+');', 'input '+','.join(inputs)+';', 'output '+','.join(outputs)+';']
    internal=[name for name in signals if name not in outputs]
    if internal: text.append('wire '+','.join(internal)+';')
    for i,(name,kind,fanin) in enumerate(gates):
        text.append('FAN_'+kind+str(len(fanin))+' u'+str(i)+' ('+','.join(['.A'+str(j)+'('+v+')' for j,v in enumerate(fanin)]+['.Z('+name+')'])+');')
    text.append('endmodule')
    path.write_text('\n'.join(text), encoding='utf-8')
    return str(path)

def finish(native, ranked=False):
    steps=[]
    while native.remaining_fault_ids():
        phase=native.begin_step(native.remaining_fault_ids()[0])
        while phase['phase']=='dtc':
            order=phase['dtc_candidate_fault_ids']
            phase=native.rank_dtc_candidates(list(reversed(order)) if ranked else order)
        steps.append(phase)
    return native.result(),steps

def test_original_catalog_graph_and_pin_order(tmp_path):
    p=write_verilog(tmp_path,['a','b'],['z'],[('z','AND',['b','a'])])
    graph=cpp_fan.circuit_graph(p,LIB)
    assert graph['schema']=='fan_circuit_graph_v1'
    assert graph['input_names']==['a','b'] and graph['output_names']==['z']
    assert [g['gate_id'] for g in graph['gates']]==list(range(4))
    assert graph['gates'][2]['kind']=='AND2'
    assert graph['gates'][2]['fanins']==[1,0]
    cat=cpp_fan.catalog_stuck_at(p,LIB)
    entries={f['fault_id']:f for f in cat['faults']}
    assert cat['uncollapsed_total']==12
    assert sum(f['eqv_fault_num'] for f in entries.values())==12
    assert entries['g2:GI0:sa1']['input_wire_name']=='g1'
    assert entries['g2:GI1:sa1']['input_wire_name']=='g0'
    assert entries['g3:GI0:sa0']['boundary_type']=='PO'
    s=cpp_fan.StuckAtSession(p,LIB)
    assert s.config()['protocol_version']=='fan_verilog_fullscan_v3'
    result,_=finish(s)
    assert result['detected_equivalent_faults']==12
    assert result['pattern_count']==3
    assert s.result()==s.result()

@pytest.mark.parametrize('seed',range(12))
def test_reconvergent_native_fault_simulation(tmp_path,seed):
    rng=random.Random(seed); signals=list('abcd')+['root']; gates=[('root','AND',list('abcd'))]
    for i in range(10):
        fi=rng.choices(signals,k=2); name='n'+str(i)
        gates.append((name,rng.choice(['AND','NAND','OR','NOR','XOR','XNOR']),fi));signals.append(name)
    p=write_verilog(tmp_path,list('abcd'),[name for name,_,_ in gates],gates)
    s=cpp_fan.StuckAtSession(p,LIB); result,steps=finish(s,True)
    graph=cpp_fan.circuit_graph(p,LIB)
    actual=coverage(graph,result['test_vectors'],result['input_names'])
    exhaustive=coverage(graph,[''.join(x) for x in itertools.product('01',repeat=4)])
    assert actual['total']==result['uncollapsed_faults']
    assert actual['detected']==result['detected_equivalent_faults']
    assert actual['detected']<=exhaustive['detected']
    assert all(len(x['dtc_attempted_fault_ids'])==len(set(x['dtc_attempted_fault_ids'])) for x in steps)

def test_rank_validation_and_one_wire_budget(tmp_path):
    p=write_verilog(tmp_path,list('abcd'),['x','y','z'],[('x','AND',['a','b']),('y','AND',['c','d']),('z','AND',['y','c'])])
    graph=cpp_fan.circuit_graph(p,LIB); s=cpp_fan.StuckAtSession(p,LIB)
    phase=s.begin_step('g0:GO:sa0'); assert phase['phase']=='dtc'
    with pytest.raises(ValueError,match='permutation'): s.rank_dtc_candidates([])
    po=graph['output_gate_ids'][graph['output_names'].index(phase['unknown_po_id'])]
    driver='g'+str(graph['gates'][po]['fanins'][0])
    expected=[f['fault_id'] for f in s.catalog()['faults'] if (f['io']==1 and f['node_name']==driver) or (f['io']==0 and f['input_wire_name']==driver)]
    assert phase['dtc_candidate_fault_ids']==expected
    seen=set()
    while phase['phase']=='dtc':
        assert phase['visited_wire_count']==phase['select_fault_try']==1
        phase=s.rank_dtc_candidates(phase['dtc_candidate_fault_ids'])
        attempted=phase['last_dtc_attempted_fault_ids']; assert not seen.intersection(attempted);seen.update(attempted)
    assert phase['primary_podem_calls']==1
    with pytest.raises(ValueError,match='not remaining'): s.step('g0:GO:sa0')

def test_rejected_legacy_and_bad_original_frontend(tmp_path):
    p=write_verilog(tmp_path,['a'],['z'],[('z','NOT',['a'])])
    with pytest.raises(ValueError,match='library_path'): cpp_fan.catalog_stuck_at(p,'')
    with pytest.raises(TypeError): cpp_fan.catalog_stuck_at(p)
    old=tmp_path/'old.bench';old.write_text('INPUT(a)\nOUTPUT(a)\n')
    with pytest.raises(ValueError,match='BENCH'): cpp_fan.catalog_stuck_at(str(old),LIB)
    with pytest.raises(ValueError,match='all catalog'): cpp_fan.run_stuck_at_ordered(p,LIB,[])
    bad=tmp_path/'bad.v';bad.write_text('/* unclosed comment')
    with pytest.raises(ValueError,match='read/check'): cpp_fan.circuit_graph(str(bad),LIB)
    # A failed parse must not poison the original scanners for the next read.
    assert cpp_fan.circuit_graph(p,LIB)['input_names']==['a']

def test_duplicate_native_pin_occurrences(tmp_path):
    p=write_verilog(tmp_path,['a'],['z'],[('z','XOR',['a','a'])])
    cat=cpp_fan.catalog_stuck_at(p,LIB)
    pins=[f for f in cat['faults'] if f['gate_id']==1 and f['io']==0 and f['fault_type']==0]
    assert [f['input_occurrence'] for f in pins]==[0,1]

@pytest.mark.parametrize('reserved',['CK','test_si','test_se'])
def test_reserved_original_scan_ports_rejected(tmp_path,reserved):
    p=write_verilog(tmp_path,['a',reserved],['z'],[('z','AND',['a',reserved])])
    with pytest.raises(ValueError,match='reserved'): cpp_fan.circuit_graph(p,LIB)

def test_cycle_and_multiple_driver_rejection(tmp_path):
    p=write_verilog(tmp_path,['a'],['z'],[('x','AND',['a','z']),('z','NOT',['x'])])
    with pytest.raises(ValueError,match='cycle'): cpp_fan.circuit_graph(p,LIB)
    Path(p).write_text('module top(a,b,z); input a,b; output z; FAN_NOT1 u (.A0(a),.Z(z)); FAN_NOT1 v (.A0(b),.Z(z)); endmodule')
    with pytest.raises(ValueError,match='multiple'): cpp_fan.circuit_graph(p,LIB)


def test_missing_technology_pin_rejected(tmp_path):
    p=tmp_path/'missing.v'
    p.write_text('module top(a,z); input a; output z; FAN_AND2 u (.A0(a),.Z(z)); endmodule')
    with pytest.raises(ValueError,match='unconnected'): cpp_fan.circuit_graph(str(p),LIB)


def test_failed_mdt_exclusive_state_is_reset(tmp_path):
    p=write_verilog(tmp_path,['a'],['z'],[('z','NOT',['a'])])
    bad=tmp_path/'bad.mdt'; bad.write_text('scan_definition ( ( unfinished')
    with pytest.raises(ValueError): cpp_fan.circuit_graph(p,str(bad))
    assert cpp_fan.circuit_graph(netlist_path=p,library_path=LIB)['input_names']==['a']
