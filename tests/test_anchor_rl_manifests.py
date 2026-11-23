import json
from pathlib import Path

from fault_order_rl.trainer import DEFAULT_VALIDATION_MANIFEST


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ["b12_nangate45", "b15_nangate45", "b20_nangate45", "b21_nangate45", "b22_nangate45"]


def test_fan_default_and_full_validation_manifests():
    assert DEFAULT_VALIDATION_MANIFEST.name == "fan_validation_full.json"
    payload = json.loads(
        DEFAULT_VALIDATION_MANIFEST.read_text(encoding="utf-8")
    )
    assert payload["backend"] == "FAN"
    assert payload["version"] == 2 and payload["input_format"] == "verilog"
    assert len(payload["circuits"]) == 5
    full = json.loads((ROOT / "configs" / "fan_validation_full.json").read_text())
    assert [entry["name"] for entry in full["circuits"]] == EXPECTED
    assert all((ROOT / "configs" / item["netlist"]).is_file() for item in full["circuits"])


