"""Command line entry point: validate inputs, train once, test independently."""

import argparse
import json
from pathlib import Path
import sys

from .data import load_all_circuits, load_manifest
from .environment import FanEnvironment
from .trainer import (TrainConfig, Trainer,
                      evaluate_checkpoint)
from .testing import (DEFAULT_TEST_DIR, DEFAULT_LIBRARY, discover_test_manifest,
                      prepare_test_features)


def _print_evaluation_by_circuit(report):
    columns = (
        ("circuit", "circuit"),
        ("checkpoint", "checkpoint_kind"),
        ("round", "round"),
        ("native_cov", "native_fault_coverage"),
        ("model_cov", "model_fault_coverage"),
        ("cov_delta_pp", "fault_coverage_increase_percentage_points"),
        ("native_patterns", "native_pattern_count"),
        ("model_patterns", "model_pattern_count"),
        ("pattern_reduction", "pattern_reduction"),
        ("reduction_pct", "pattern_reduction_percent"),
    )
    print("\t".join(label for label, _ in columns))
    for comparison in report["comparison_by_circuit"].values():
        values = []
        for _, key in columns:
            value = comparison[key]
            if value is None:
                values.append("N/A")
            elif key in ("native_fault_coverage", "model_fault_coverage"):
                values.append("{:.6%}".format(value))
            elif key in ("fault_coverage_increase_percentage_points",
                         "pattern_reduction_percent"):
                values.append("{:+.6f}".format(value))
            else:
                values.append(str(value))
        print("\t".join(values))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Dynamic BFS-filtered ranked-DTC actor-critic PPO with FAN: configurable rounds, "
            "4-circuit rollout batches, 128-transition PPO minibatches, "
            "normalized entropy, TensorBoard monitoring, Primary backtrack=100, "
            "DTC secondary backtrack=50, schema=10; training has no test evaluation"
        ))
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate all artifacts without ATPG episodes")
    validate.add_argument("--manifest", type=Path, required=True)
    train = commands.add_parser("train")
    source = train.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--resume", type=Path)
    train.add_argument("--output", type=Path)
    train.add_argument("--rounds", type=int, default=None, help="Positive training rounds (default: 1)")
    evaluate = commands.add_parser(
        "test", aliases=["evaluate"], help="Independent testing of final/latest on arbitrary netlists")
    evaluate.add_argument("--checkpoint", type=Path, required=True)
    evaluate.add_argument("--manifest", type=Path,
                          help="Evaluate the checkpoint on a separate manifest")
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--test-dir",type=Path,default=DEFAULT_TEST_DIR)
    evaluate.add_argument("--library",type=Path,default=DEFAULT_LIBRARY)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            circuits = load_all_circuits(manifest, FanEnvironment(manifest.module_dir))
            print(json.dumps({"validated": len(circuits), "faults": {c.name: c.fault_count for c in circuits}}, indent=2))
        elif args.command == "train":
            if args.resume:
                if args.output is not None:
                    raise ValueError("resume preserves the saved output and fixed configuration")
                trainer = Trainer.resume(args.resume, rounds=args.rounds)
            else:
                if args.output is None:
                    raise ValueError("new training requires --output")
                trainer = Trainer.create(
                    args.manifest, TrainConfig(rounds=1 if args.rounds is None else args.rounds), args.output)
            report = trainer.train()
            print(json.dumps({"checkpoint_kind": report["checkpoint_kind"],
                              "round": report["round"],
                              "model_evaluation_executed": False,
                              "training_patterns": report["totals"]["pattern_count"]}, indent=2))
        else:
            if args.output is not None:
                output = args.output
            elif args.manifest is not None:
                output = (args.checkpoint.resolve().parent
                          / ("evaluation-" + args.manifest.stem))
            else:
                output = args.checkpoint.resolve().parent / "evaluation"
            manifest=args.manifest
            if manifest is None:
                manifest=discover_test_manifest(args.test_dir,args.library,Path(output)/"test_manifest.json")
            prepare_test_features(manifest)
            report = evaluate_checkpoint(args.checkpoint, output, manifest=manifest)
            _print_evaluation_by_circuit(report)
    except KeyboardInterrupt:
        print("Interrupted; resume from the last committed latest.pt.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
