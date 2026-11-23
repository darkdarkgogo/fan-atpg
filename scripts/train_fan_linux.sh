#!/usr/bin/env bash
# Explicit training entry point. Run this only when ready to train.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-python3}"
output="${1:-runs/fan_linux}"
rounds="${2:-1}"
train_manifest="${3:-configs/fan_train_full.json}"
if [[ -f "$output/latest.pt" ]]; then
  exec "$python_bin" -m fault_order_rl train --resume "$output/latest.pt" --rounds "$rounds"
fi
exec "$python_bin" -m fault_order_rl train \
  --manifest "$train_manifest" \
  --rounds "$rounds" --output "$output"
