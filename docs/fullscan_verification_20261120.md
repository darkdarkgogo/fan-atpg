# Fullscan validation verification

Implemented the approved single-capture fullscan interface and replaced the
legacy validation netlists with b12/b15/b20/b21/b22 Nangate45 capture views.

- Python extension rebuilt with the project's Python 3.9 interpreter.
- Original Linux FAN CLI rebuilt serially in Ubuntu WSL.
- Full pytest suite: **157 passed**.
- Independent code review identified FF/constant ordering and constant-cone
  justification defects; both were fixed and covered by focused regressions.
- Reviewer additionally ran 100 deterministic random binary-constant circuits
  with DTC on/off: **200 complete ATPG/STC sessions**. Independent simulation
  matched native fault totals and detections; each matched exhaustive reachable
  coverage. No crashes or false coverage credit were observed.
- Five validation graphs, fault catalogs and pinned DeepGate2 exports are
  checked by `validation/reports/verilog_validation_inputs.json` and the feature
  preparation/manifest validation commands. Features are ready in
  `datasets/verilog_features/validation` on this machine.
- Original CLI read/build checks passed for all five netlists; see
  `datasets/itc99_nangate45/validation_cli_load.json`.
- Large-circuit checks use 32 sampled AIG-equivalence vectors per circuit and
  target ATPG sampled across each functional catalog, with independent
  verification of accepted target vectors. See
  `datasets/itc99_nangate45/validation_large.json` for exact counts.
  The final run independently verified 135 accepted target vectors.
- No full large-circuit ATPG coverage claim or PPO training run is made.

Protocol is `fan_verilog_fullscan_v3`, checkpoint schema 9. Old schema 8
checkpoints cannot be resumed as this protocol. The ten old `_C` source
netlists were deleted; hashes and exact paths are recorded in
`datasets/itc99_nangate45/deleted_legacy_validation.json`.
