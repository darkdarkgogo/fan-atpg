#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-python3}"
checkpoint="${1:?Usage: test_fan_linux.sh <final.pt> [test_dir] [output_dir] [library.mdt]}"
test_dir="${2:-FAN_ATPG/netlist/iscas_test}"
output="${3:-runs/fan_test}"
library="${4:-FAN_ATPG/techlib/mod_nangate45.mdt}"
runtime_args=(--device "${DEVICE:-auto}" --inference-chunk-size "${INFERENCE_CHUNK_SIZE:-16384}")
if [[ -n "${THREADS:-}" ]]; then runtime_args+=(--threads "$THREADS"); fi
if [[ -n "${FEATURE_DEVICE:-}" ]]; then runtime_args+=(--feature-device "$FEATURE_DEVICE"); fi
exec "$python_bin" -m fault_order_rl test --checkpoint "$checkpoint" \
  --test-dir "$test_dir" --library "$library" --output "$output" "${runtime_args[@]}"
