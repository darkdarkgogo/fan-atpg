# FAN migration implementation plan

Goal: run the existing full dynamic fault reorder workflow on the FAN solver, with one training round and one validation.
Architecture: preserve feature and PPO logic; add cpp_fan stateful native solver plus FAN-specific artifact exporter and protocol identity.
Spec: docs/superpowers/specs/2026-11-20-fan-migration-design.md

## Global constraints
- Original fault-reorder is read-only.
- Native FAN performs all target solving; no PODEM fallback or fake features.
- One training round and one validation round.
- Use native catalog for FAN fault metadata; independently check coverage.

## Task 1: native FAN backend
- [x] Modify FAN_ATPG/pkg/core/src/atpg.{h,cpp} for selectable primary and phased BFS DTC.
- [x] Create FAN_ATPG/python binding and build entry point cpp_fan.
- [x] Implement catalog, cumulative results, backtrack counters, safe cube restore and STC.
- [x] Build on available Linux environment; exercise native phases and coverage.

## Task 2: training framework migration
- [x] Adapt fault_order_rl environment/data/trainer/CLI/checkpoint identity to FAN.
- [x] Accept --rounds 1 with one validation at round end; preserve PPO and strict executed prefix semantics.
- [x] Preserve complete artifacts and add focused protocol/config tests.

## Task 3: FAN feature preparation
- [x] Export fault feature metadata from cpp_fan catalog aligned to original BENCH and pinned official DeepGate2.
- [x] Create disjoint train/validation manifests with command-line preparation workflow.
- [x] Validate ID, polarity, pin, equivalent count and provenance consistency.

## Task 4: end-to-end acceptance
- [x] Compile backend and run focused meaningful integration tests.
- [x] Train one complete round and validate once on disjoint real circuits.
- [x] Independently simulate saved patterns and verify post-STC coverage.
- [x] Review code, resolve important findings, document results and reproduction commands.

