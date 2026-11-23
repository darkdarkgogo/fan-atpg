"""Exhaustive physical checks; no learning or model evaluation."""
from itertools import product
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'FAN_ATPG'))
cpp_fan=pytest.importorskip('cpp_fan')
from validation.independent_sim import coverage
LIB=str(Path(__file__).resolve().parents[1]/'datasets/verilog/fan_primitives.mdt')

@pytest.mark.parametrize('kind,n', [('NOT',1),('BUF',1)]+[(k,n) for k in ['AND','NAND','OR','NOR'] for n in [2,3,4]]+[(k,n) for k in ['XOR','XNOR'] for n in [2,3]])
def test_all_supported_boolean_primitives(tmp_path,kind,n):
    names=['a'+str(i) for i in range(n)]
    p=tmp_path/'tiny.v'
    p.write_text('module top('+','.join(names+['z'])+'); input '+','.join(names)+'; output z; FAN_'+kind+str(n)+' u ('+','.join(['.A'+str(i)+'('+v+')' for i,v in enumerate(names)]+['.Z(z)'])+'); endmodule')
    graph=cpp_fan.circuit_graph(str(p),LIB)
    session=cpp_fan.StuckAtSession(str(p),LIB)
    while session.remaining_fault_ids(): session.step(session.remaining_fault_ids()[0])
    final=session.result()
    actual=coverage(graph,final['test_vectors'],final['input_names'])
    exhaustive=coverage(graph,[''.join(p) for p in product('01',repeat=n)])
    assert actual['total']==final['uncollapsed_faults']
    assert actual['detected']==final['detected_equivalent_faults']
    assert actual['detected']==exhaustive['detected']

@pytest.mark.parametrize('value',[0,1])
def test_constant_native_semantics(tmp_path,value):
    library=tmp_path/'constant.mdt'
    library.write_text(Path(LIB).read_text()+ '\nmodel CONST (Z) ( output (Z) ( primitive = _tie'+str(value)+' p (Z); ) )\n')
    p=tmp_path/'constant.v'
    p.write_text('module top(a,z,k); input a; output z,k; CONST c (.Z(k)); FAN_AND2 u (.A0(a),.A1(k),.Z(z)); endmodule')
    graph=cpp_fan.circuit_graph(str(p),str(library))
    from fault_embedding.native_aig import lower_native_circuit, verify_native_equivalence
    verify_native_equivalence(graph,lower_native_circuit(graph))
    from validation.independent_sim import read_circuit, evaluate
    for a in (0,1):
        assert evaluate(read_circuit(graph),[a],1)==[a & value,value]
    session=cpp_fan.StuckAtSession(str(p),str(library))
    while session.remaining_fault_ids():
        session.step(session.remaining_fault_ids()[0])
    result=session.result()
    actual=coverage(graph,result['test_vectors'])
    exhaustive=coverage(graph,['0','1'])
    assert actual['total']==result['uncollapsed_faults']
    assert actual['detected']==result['detected_equivalent_faults']==exhaustive['detected']

@pytest.mark.parametrize('primitive', ['tiex','tiez','mux','dff'])
def test_unsupported_original_primitives_fail_explicitly(tmp_path,primitive):
    library=tmp_path/'unsupported.mdt'
    if primitive in ['tiex','tiez']:
        model='model BAD (Z) ( output (Z) ( primitive = _'+primitive+' p (Z); ) )'
        circuit='module top(a,z,k); input a; output z,k; BAD c (.Z(k)); FAN_AND2 u (.A0(a),.A1(k),.Z(z)); endmodule'
    elif primitive=='mux':
        model='model BAD (A,B,S,Z) (input (A,B,S) () output (Z) (primitive = _mux p (A,B,S,Z);))'
        circuit='module top(a,b,s,z); input a,b,s; output z; BAD u (.A(a),.B(b),.S(s),.Z(z)); endmodule'
    else:
        model='model BAD (D,CK,Q) (input (D,CK) () output (Q) (primitive = _dff p (,,CK,D,Q,);))'
        circuit='module top(d,CK,z); input d,CK; output z; BAD u (.D(d),.CK(CK),.Q(z)); endmodule'
    library.write_text(Path(LIB).read_text()+'\n'+model+'\n')
    p=tmp_path/'unsupported.v';p.write_text(circuit)
    with pytest.raises(ValueError,match='unsupported'):
        cpp_fan.circuit_graph(str(p),str(library))


def test_original_standard_library_multi_primitive_cell(tmp_path):
    library=str(Path(__file__).resolve().parents[1]/'FAN_ATPG/techlib/mod_nangate45.mdt')
    p=tmp_path/'aoi.v';p.write_text('module top(a,b,c,z); input a,b,c; output z; AOI21_X1 u (.A(a),.B1(b),.B2(c),.ZN(z)); endmodule')
    graph=cpp_fan.circuit_graph(str(p),library)
    from fault_embedding.native_aig import lower_native_circuit, verify_native_equivalence
    verify_native_equivalence(graph,lower_native_circuit(graph))
    from validation.independent_sim import read_circuit, evaluate
    for bits in product('01',repeat=3):
        values=evaluate(read_circuit(graph),[int(b) for b in bits],1)
        expected=1-(int(bits[0]) | (int(bits[1]) & int(bits[2])))
        assert values[0]==expected
    s=cpp_fan.StuckAtSession(str(p),library)
    while s.remaining_fault_ids(): s.step(s.remaining_fault_ids()[0])
    final=s.result()
    assert coverage(graph,final['test_vectors'],final['input_names'])['detected']==final['detected_equivalent_faults']


def test_direct_port_alias_without_cells(tmp_path):
    p=tmp_path/'direct.v';p.write_text('module top(a,z); input a; output z; assign z=a; endmodule')
    graph=cpp_fan.circuit_graph(str(p),LIB)
    assert [(g['kind'],g['fanins']) for g in graph['gates']]==[('PI',[]),('PO',[0])]
    s=cpp_fan.StuckAtSession(str(p),LIB)
    while s.remaining_fault_ids(): s.step(s.remaining_fault_ids()[0])
    final=s.result()
    assert coverage(graph,final['test_vectors'])['detected']==final['detected_equivalent_faults']==4

def test_fixed_supply_cone_first_target(tmp_path):
    p=tmp_path/'fixed.v'
    p.write_text('''module top(a,b,c,k0,n2,n4,n5); input a,b,c; output k0,n2,n4,n5;
NOR2_X1 u2 (.A1(k0),.A2(b),.ZN(n2));
NOR2_X1 u4 (.A1(c),.A2(n2),.ZN(n4));
AND2_X1 u5 (.A1(n4),.A2(a),.ZN(n5)); LOGIC0_X1 t0 (.Z(k0)); endmodule''')
    lib=str(Path(__file__).resolve().parents[1]/'FAN_ATPG/techlib/mod_nangate45.mdt')
    graph=cpp_fan.circuit_graph(str(p),lib)
    session=cpp_fan.StuckAtSession(str(p),lib,dtc_enabled=False)
    assert session.step('g0:GO:sa0')['target_status']=='detected'
    while session.remaining_fault_ids(): session.step(session.remaining_fault_ids()[0])
    result=session.result()
    actual=coverage(graph,result['test_vectors'])
    exhaustive=coverage(graph,[''.join(b) for b in product('01',repeat=3)])
    assert actual['detected']==result['detected_equivalent_faults']==exhaustive['detected']
