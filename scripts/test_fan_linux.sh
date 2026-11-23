#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-python3}"
checkpoint="${1:?Usage: test_fan_linux.sh <final.pt> [test_dir] [output_dir] [library.mdt]}"
test_dir="${2:-FAN_ATPG/netlist/test}"
output="${3:-runs/fan_test}"
library="${4:-FAN_ATPG/techlib/mod_nangate45.mdt}"
exec "$python_bin" -m fault_order_rl test --checkpoint "$checkpoint" \
  --test-dir "$test_dir" --library "$library" --output "$output"
