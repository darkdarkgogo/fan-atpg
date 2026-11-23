# FAN Verilog migration implementation plan

Goal: original FAN Verilog/library frontend, no added BENCH training interface, no training execution.
Architecture: real FAN netlist frontend exports internal primitive graph for AIG embeddings; version2 manifests and schema8 checkpoints isolate old data.
Tech stack: C++14, original flex/bison interface, pybind11, Python, pinned DeepGate2.
Spec: docs/superpowers/specs/2026-11-20-fan-verilog-design.md

## Global constraints
- Do not run training or PPO optimization, including training-loop unit tests.
- Original Verilog/library frontend must actually be used.
- Remove native Bench builder and old BENCH training config path.
- Keep official pretrained encoder bytes unchanged.

## Task1 Native frontend
- [x] Replace Bench with original Techlib/Netlist/Circuit builders, include required interface/parser sources in setup.
- [x] Expose graph/catalog stable native IDs and v2 protocol; reject BENCH and missing library.
- [x] Build and verify parser/library against original CLI, preserve existing DTC/STC physical safety.

## Task2 AIG feature pipeline
- [x] Directly lower exported native Circuit graph to AIG JSON; resolve FAN fault anchors with gate/pin IDs.
- [x] Rework prepare_fan_data.py for manifest2 Verilog/library, immutable provenance, no BENCH roundtrip.
- [x] Add graph/catalog/Boolean-equivalence tests and coordinate validator with Task3.

## Task3 Python environment/data
- [x] New CircuitSpec(netlist_path,library_path,embeddings_path,metadata_path,graph_path), strict manifest2.
- [x] Propagate library through catalog/session/trainer, isolate protocol2/schema8 from old artifacts.
- [x] Update applicable non-training tests; no optimizer or training-loop execution.

## Task4 Corpus/Linux/package acceptance
- [x] Generate mapped structural Verilog corpus plus explicit MDT library; update configs/generators and independent simulation.
- [x] Update Linux scripts/docs and package to contain active Verilog data only.
- [x] Validate native imports, real features, independent simulation, config checks and source/package consistency; do not train.
