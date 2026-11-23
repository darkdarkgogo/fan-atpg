"""Test inputs are discovered by format, never a benchmark name whitelist."""
import json
from pathlib import Path
from fault_order_rl.testing import discover_test_manifest
from fault_order_rl.data import load_manifest
import pytest

def test_open_test_directory_accepts_new_circuits(tmp_path):
    directory=tmp_path/'netlist'; directory.mkdir()
    library=tmp_path/'cells.mdt'; library.write_text('placeholder library')
    (directory/'my_custom_design.v').write_text('module custom; endmodule')
    (directory/'README.md').write_text('not a netlist')
    output=tmp_path/'configs/test.json'
    discover_test_manifest(directory,library,output)
    assert [c.name for c in load_manifest(output).circuits]==['my_custom_design']
    (directory/'anything_else.sv').write_text('module next; endmodule')
    discover_test_manifest(directory,library,output)
    assert {c.name for c in load_manifest(output).circuits}=={'my_custom_design','anything_else'}

def test_same_stem_different_directory_or_content_has_distinct_cache(tmp_path):
    library=tmp_path/'cells.mdt';library.write_text('library')
    output=tmp_path/'test.json'
    paths=[]
    for name in ('one','two'):
        folder=tmp_path/name;folder.mkdir()
        (folder/'top.v').write_text('module '+name+'; endmodule')
        discover_test_manifest(folder,library,output)
        paths.append(load_manifest(output).circuits[0].embeddings_path)
    assert paths[0]!=paths[1]
    (tmp_path/'one/top.v').write_text('module replacement; endmodule')
    discover_test_manifest(tmp_path/'one',library,output)
    assert load_manifest(output).circuits[0].embeddings_path not in paths

def test_casefold_stem_collision_is_rejected(tmp_path):
    library=tmp_path/'cells.mdt';library.write_text('library')
    (tmp_path/'top.v').write_text('module top; endmodule')
    (tmp_path/'TOP.sv').write_text('module top2; endmodule')
    with pytest.raises(ValueError,match='Duplicate'):
        discover_test_manifest(tmp_path,library,tmp_path/'test.json')

def test_external_drive_manifest_supports_absolute_paths(tmp_path,monkeypatch):
    library=tmp_path/'cells.mdt';library.write_text('library')
    (tmp_path/'top.v').write_text('module top; endmodule')
    import fault_order_rl.testing as testing
    def different_drive(*args):raise ValueError('different drives')
    monkeypatch.setattr(testing.os.path,'relpath',different_drive)
    output=tmp_path/'configs/test.json'
    discover_test_manifest(tmp_path,library,output)
    spec=load_manifest(output).circuits[0]
    assert spec.netlist_path==tmp_path/'top.v'
    assert spec.library_path==library

def test_default_test_manifest_has_existing_files():
    root=Path(__file__).resolve().parents[1]
    payload=json.loads((root/'configs/fan_test.json').read_text())
    assert payload['backend']=='FAN' and payload['input_format']=='verilog'
    assert payload['circuits']
    for item in payload['circuits']:
        assert (root/'configs'/item['netlist']).is_file()
        assert (root/'configs'/item['library']).is_file()
