# GPU Runtime Implementation Plan

**Goal:** Use CUDA automatically for neural computation and allow CPU threads.
**Spec:** ../specs/2026-11-24-gpu-runtime-design.md
**Execution:** Inline implementation, followed by an independent code review.

- [x] Add shared device/thread resolution, CUDA RNG checkpoint support and CLI
  controls; retain schema-10 checkpoint compatibility and permit CPU/CUDA build
  variants of the same PyTorch release.
- [x] Move policy and PPO computation onto the selected device; transfer only
  active circuit embeddings, chunk evaluation scoring with complete-set context,
  and keep selection/bookkeeping on CPU using one score transfer per step.
- [x] Add extraction device support with device-specific DeepGate cache keys,
  correct RNG/thread restoration and accurate export provenance.
- [x] Propagate controls through Linux scripts; document matching CUDA PyTorch
  and PyG installation using official sources and add visible runtime/timing logs.
- [x] Test CPU end-to-end behavior, legacy checkpoints, chunk parity, CLI controls,
  and optional CUDA forward/backward/resume/extraction; obtain code review and
  fix findings. Report unavailable GPU verification explicitly.

Completed: 179 tests passed in the project d2l environment, including real CUDA
and native FAN/DeepGate2 integration. Independent review completed; resume thread
preservation finding fixed. Details: ../../gpu-runtime-validation-20261124.md.
