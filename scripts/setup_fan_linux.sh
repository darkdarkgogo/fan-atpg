#!/usr/bin/env bash
# Build and import-check only. This script never starts training.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="${PYTHON:-python3}"
command -v c++ >/dev/null || { echo 'A C++14 compiler (g++) is required.' >&2; exit 1; }
"$python_bin" - <<'PY'
import os, sys, sysconfig
assert sys.version_info >= (3, 9), 'Python 3.9+ is required'
import setuptools, numpy, torch, torch_geometric, torch_scatter, torch_sparse
import tensorboard
header = os.path.join(sysconfig.get_path('include'), 'Python.h')
assert os.path.isfile(header), 'Missing Python development header: ' + header
print('Python:', sys.executable)
print('PyTorch:', torch.__version__)
print('CUDA build:', torch.version.cuda, 'CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('GPU:', torch.cuda.get_device_name(0))
PY
"$python_bin" FAN_ATPG/setup.py build_ext --inplace
"$python_bin" - <<'PY'
import sys
sys.path.insert(0, 'FAN_ATPG')
import cpp_fan
assert all(hasattr(cpp_fan, n) for n in ('catalog_stuck_at', 'StuckAtSession', 'run_stuck_at_ordered', 'circuit_graph'))
print('FAN Verilog/MDT Linux extension ready:', cpp_fan.__file__)
print('Build/check complete. No training was started.')
PY
