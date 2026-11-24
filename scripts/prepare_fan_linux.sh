#!/usr/bin/env bash
# Export/check features only. This script never starts training.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-python3}"
train_manifest="${1:-configs/fan_train_full.json}"
runtime_args=(--device "${FEATURE_DEVICE:-${DEVICE:-auto}}")
if [[ -n "${THREADS:-}" ]]; then runtime_args+=(--threads "$THREADS"); fi
for manifest in "$train_manifest"; do
  "$python_bin" scripts/prepare_fan_data.py --manifest "$manifest" "${runtime_args[@]}"
  "$python_bin" -m fault_order_rl validate --manifest "$manifest"
done
echo 'Feature preparation complete. No training was started.'
