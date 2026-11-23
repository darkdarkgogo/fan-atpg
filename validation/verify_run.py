"""Verify persisted training/validation patterns without rerunning the policy."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validation.independent_sim import coverage


def verify(graph, metrics):
    observed = coverage(graph, metrics["test_vectors"], metrics["input_names"])
    observed.pop("detected_faults")
    observed["native_detected"] = metrics["detected_equivalent_faults"]
    observed["native_total"] = metrics["uncollapsed_faults"]
    observed["matches_native"] = (
        observed["detected"] == observed["native_detected"]
        and observed["total"] == observed["native_total"]
        and observed["patterns"] == metrics["patterns_after_stc"])
    if not observed["matches_native"]:
        raise RuntimeError("Independent fault simulation disagrees: " + str(observed))
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--train-manifest", type=Path, default=ROOT / "configs/fan_train.json")
    parser.add_argument("--validation-manifest", type=Path, default=ROOT / "configs/fan_validation.json")
    args = parser.parse_args()
    locations = {}
    for path in (args.train_manifest, args.validation_manifest):
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        if manifest.get("version") != 2 or manifest.get("input_format") != "verilog":
            raise ValueError("Expected Verilog manifest version2")
        for item in manifest["circuits"]:
            locations[item["name"]] = (path.parent / item["graph"]).resolve()
    report = {"method": "independent Python bit-parallel uncollapsed stuck-at simulation",
              "training": {}, "validation": {}, "validation_baseline": {}}
    for path in sorted((args.run / "rounds").glob("round-*/*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") != "episode":
            continue
        name = raw["circuit"]
        report["training"][str(path.relative_to(args.run))] = verify(locations[name], raw)
    for path in sorted((args.run / "validation").glob("round-*/summary.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for group, key in (("validation", "circuits"), ("validation_baseline", "native_metrics")):
            for name, metrics in raw[key].items():
                label = str(path.parent.relative_to(args.run)) + "/" + name
                report[group][label] = verify(locations[name], metrics)
    if not report["training"] or not report["validation"]:
        raise RuntimeError("Missing persisted training or validation results")
    output = args.run / "independent_coverage.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
