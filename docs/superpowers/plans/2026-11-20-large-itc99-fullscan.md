# Large ITC99 Fullscan Implementation Plan

> Execute inline in the existing checkout; use requesting-code-review for independent review. User authorized implementation and dataset replacement.

**Goal:** Replace legacy combinational validation circuits with five Nangate45 scan netlists and support single-frame fullscan PPO validation.

**Architecture:** Original Verilog/MDT parsing and Circuit build; normalize PPI/PPO boundaries in the bridge without changing gate IDs, preserve scan metadata, use existing functional ATPG and simulation.

**Tech Stack:** C++14, pybind11, Python 3.9+, Yosys 0.52, Nangate45 MDT, pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-large-itc99-fullscan-design.md`

## Tasks

1. Import and synthesize pinned b12,b15,b20,b21,b22 RTL using `datasets/itc99_nangate45/rebuild.sh`; preserve original RTL and report any required repairs. Run Yosys `check -assert`, native read/build smoke, record actual gate/FF counts.
2. Add `tests/test_fullscan_native.py` with a two-FF feedback circuit. Assert state bits follow true PIs, next-state outputs follow true POs, scan-only faults excluded, native AIG equivalent, independent exhaustive fault detection agrees. Run failing tests before bridge changes.
3. Adapt `FAN_ATPG/python/bindings.cpp`: validate full chain, cut feedback for cycle checking, permit optional unused QN and exact binary ties, normalize native scan boundaries, export scan metadata, remove synthetic protocol faults. Preserve primitive arity, driver and cycle guards. Upgrade protocol/checkpoint bindings and update tests that deliberately rejected now-supported binary constants/fullscan.
4. Rebuild extension with the existing conda Python. Run scan tests plus `tests/test_fan_native.py`, `tests/test_fan_acceptance.py`, AIG, independent simulation and checkpoint regressions. Fix failures before broadening checks.
5. Update full validation manifest to five scan netlists, delete exactly the ten old `_C` source netlists and any matching feature caches after resolving every target inside the workspace. Save deletion audit and update source provenance and documentation. Update manifest regression expectations.
6. Validate all new inputs through the Python bridge, export graphs/catalogs, generate validation features with fixed DeepGate2 weights; do not train PPO. Review changes independently, resolve important findings, record checks and limitations in dataset README.
