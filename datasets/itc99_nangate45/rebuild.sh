#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export LD_LIBRARY_PATH="$PWD/tmp/itc99-tools/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
YOSYS="${YOSYS:-$PWD/tmp/itc99-tools/usr/bin/yosys}"
D=datasets/itc99_nangate45
LIB=$D/tools/NangateOpenCellLibrary_base.lib
targets=(b03 b04 b05 b07 b08 b09 b13 b12 b15 b20 b21 b22)
if [[ $# -gt 0 ]]; then targets=("$@"); fi
for c in "${targets[@]}"; do
  echo "Synthesizing $c"
  "$YOSYS" -Q -T -p "read_liberty -lib $LIB; read_verilog -sv $D/rtl/$c.v; hierarchy -check -top $c; synth -top $c -flatten -noabc; dfflibmap -liberty $LIB; abc -liberty $LIB -dont_use MUX2_X1; splitnets -ports; opt_clean; check -assert; write_verilog -noattr -noexpr $D/raw/$c.v" > "$D/logs/${c}_synth.log" 2>&1
  python3 "$D/tools/prepare_fan.py" "$c"
done
