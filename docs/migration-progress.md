# Migration progress — plan: docs/superpowers/plans/2026-11-20-fan-migration.md
Design approved by user request for full migration. User narrowed acceptance to one training and one validation round.
Source Python packages and vendored pinned DeepGate2/pybind11 copied. Original project untouched.
Ruling: use current workspace as explicitly requested. Native C++ in existing FAN_ATPG checkout; Python migration at workspace root. No new worktree required.
Ruling: catalog/session dictionary structure follows old production validator, while protocol and checkpoint identity explicitly identify FAN.
Shared interface scan: Task 1 produces cpp_fan catalog/session, Task 2 consumes it, Task 3 consumes catalog. Task 2 and Task 3 coordinate metadata validation format directly. Task 4 consumes all outputs. No overlapping ownership of implementation files.

Task 1: complete. Real FAN cp39 extension and original Linux CLI build verified. Correct original-wire BFS budget, native parallel simulation, STC, Unicode paths, gate-ID minimum-fanin field, bounded work, and conservative redundancy proof. Final binary SHA256 da2a73f76572d0cba575ffb65ef26b9e02d2fd79bba7be95f6ff879d77826aca.
Task 2: complete. FAN-only schema7/checkpoint isolation, configurable rounds(default1), persisted final vectors, no duplicate final validation, actual detected coverage separate from resolved metric.
Task 3: complete. Real official DeepGate2 exports for disjoint acceptance cones (474/1404 collapsed faults); full original1024+5 BENCH input corpus imported and manifests provided. Full corpus feature preparation remains an explicit later execution option, not claimed as this acceptance run.
Task 4: complete. 123 tests passed,3 legacy optional tests skipped. Independent review covers fault catalog pins, checkpoint isolation,530 individual fault redundancy classifications,80 random circuits, and scoped one-wire scheduler protocol tests.

Final authoritative run: runs/fan_migrated_20261120, exactly1 training round and1 model validation pass;4 PPO optimizer updates. Train674/692 detected,19 patterns. Validation2212/2212 detected,21 patterns vs native22, improvement1(4.5455%). Independent saved-vector simulation confirms all counts. Checkpoint solver_digest matches installed binary. One validation output directory. Earlier integration trial retained and explicitly marked superseded; no checkpoint from it is presented as final.
Ruling: use conservative ABORT for unsupported proof of native no-test claims, rather than credit unsound redundancy. This retains honest coverage and can leave detectable faults unresolved under bounded search. README documents limitation.
