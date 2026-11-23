"""Physical single-capture checks for fullscan state boundaries."""
from itertools import product
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'FAN_ATPG'))
cpp_fan = pytest.importorskip('cpp_fan')
from validation.independent_sim import coverage, read_circuit, evaluate
from fault_embedding.native_aig import lower_native_circuit, verify_native_equivalence

LIB = str(Path(__file__).resolve().parents[1] / 'FAN_ATPG/techlib/mod_nangate45.mdt')

def scan_netlist(tmp_path):
    p = tmp_path / 'scan.v'
    p.write_text('''module top(a,CK,test_si,test_se,z,test_so);
input a,CK,test_si,test_se; output z,test_so;
wire q0,q1,d0,d1;
SDFF_X1 ff0 (.D(d0),.CK(CK),.SI(test_si),.SE(test_se),.Q(q0));
SDFF_X1 ff1 (.D(d1),.CK(CK),.SI(q0),.SE(test_se),.Q(q1));
XOR2_X1 g0 (.A(a),.B(q1),.Z(d0));
AND2_X1 g1 (.A1(q0),.A2(a),.ZN(d1));
INV_X1 g2 (.A(q0),.ZN(z));
assign test_so=q1;
endmodule''')
    return p

def test_scan_state_truth_table_and_functional_catalog(tmp_path):
    p = scan_netlist(tmp_path)
    graph = cpp_fan.circuit_graph(str(p), LIB)
    assert graph['scan']['mode'] == 'fullscan_single_capture'
    assert graph['input_names'] == ['a', 'ff0/Q', 'ff1/Q']
    assert graph['output_names'] == ['z', 'ff0/D', 'ff1/D']
    verify_native_equivalence(graph, lower_native_circuit(graph))
    for a,q0,q1 in product((0,1), repeat=3):
        assert evaluate(read_circuit(graph), [a,q0,q1], 1) == [1-q0,a^q1,a&q0]
    cat = cpp_fan.catalog_stuck_at(str(p), LIB)
    assert all(f['gate_id'] >= 0 and f['input_index'] >= -1 for f in cat['faults'])
    assert sum(f['eqv_fault_num'] for f in cat['faults']) == cat['uncollapsed_total']
    for dtc in (False, True):
        s = cpp_fan.StuckAtSession(str(p), LIB, dtc_enabled=dtc)
        while s.remaining_fault_ids():
            s.step(s.remaining_fault_ids()[0])
        result = s.result()
        actual = coverage(graph, result['test_vectors'], result['input_names'])
        exhaustive = coverage(graph, [''.join(bits) for bits in product('01', repeat=3)])
        assert actual['total'] == result['uncollapsed_faults']
        assert actual['detected'] == result['detected_equivalent_faults'] == exhaustive['detected']

@pytest.mark.parametrize('change', ['chain', 'clock', 'enable', 'reset'])
def test_unsafe_scan_protocol_rejected(tmp_path, change):
    p = scan_netlist(tmp_path)
    src = p.read_text()
    if change == 'chain': src = src.replace('.SI(q0)', '.SI(test_si)')
    if change == 'clock': src = src.replace('.CK(CK)', '.CK(a)', 1)
    if change == 'enable': src = src.replace('.SE(test_se)', '.SE(a)', 1)
    if change == 'reset': src = src.replace('SDFF_X1 ff0', 'SDFFR_X1 ff0').replace('.D(d0)', '.RN(a),.D(d0)')
    p.write_text(src)
    with pytest.raises(ValueError, match='unsupported'):
        cpp_fan.circuit_graph(str(p), LIB)

def test_constant_before_scan_ff_and_inactive_reset(tmp_path):
    p=scan_netlist(tmp_path)
    src=p.read_text().replace('wire q0,q1,d0,d1;', 'wire q0,q1,d0,d1,high; LOGIC1_X1 tie (.Z(high));')
    src=src.replace('SDFF_X1 ff0','SDFFR_X1 ff0').replace('.D(d0)','.RN(high),.D(d0)')
    p.write_text(src)
    graph=cpp_fan.circuit_graph(str(p),LIB)
    assert len(graph['scan']['state_input_gate_ids'])==2
    session=cpp_fan.StuckAtSession(str(p),LIB)
    while session.remaining_fault_ids(): session.step(session.remaining_fault_ids()[0])
    result=session.result()
    actual=coverage(graph,result['test_vectors'])
    assert actual['total']==result['uncollapsed_faults']
    assert actual['detected']==result['detected_equivalent_faults']

@pytest.mark.parametrize('value',[0,1])
def test_constant_reconvergence_with_state_and_xor(tmp_path,value):
    p=scan_netlist(tmp_path)
    src=p.read_text().replace('wire q0,q1,d0,d1;',f'wire q0,q1,d0,d1,k,x; LOGIC{value}_X1 tie (.Z(k));')
    src=src.replace('XOR2_X1 g0 (.A(a),.B(q1),.Z(d0));','XOR2_X1 g0 (.A(a),.B(q1),.Z(x));\nAOI21_X1 g3 (.A(x),.B1(k),.B2(q1),.ZN(d0));')
    p.write_text(src)
    graph=cpp_fan.circuit_graph(str(p),LIB)
    session=cpp_fan.StuckAtSession(str(p),LIB)
    while session.remaining_fault_ids(): session.step(session.remaining_fault_ids()[0])
    result=session.result()
    actual=coverage(graph,result['test_vectors'])
    exhaustive=coverage(graph,[''.join(bits) for bits in product('01',repeat=3)])
    assert actual['total']==result['uncollapsed_faults']
    assert actual['detected']==result['detected_equivalent_faults']==exhaustive['detected']
