# GPU and CPU thread runtime

## Requested behavior

Training and independent testing use CUDA when available. CPU tensor operations
can use multiple threads. Existing schema-10 checkpoints remain loadable.

## Design

- Add `--device auto|cpu|cuda|cuda:N` and `--threads N` to train, resume,
  test and feature preparation. `auto` selects CUDA when available and otherwise
  reports CPU fallback. An explicitly requested unavailable CUDA device fails.
  Default CPU thread count is min(8, available CPU cores), at least one.
- Print selected device, GPU name when applicable, and CPU thread count at startup.
  Pass these controls through Linux scripts using environment variables
  `DEVICE` and `THREADS`; preserve existing positional arguments.
- Move the policy network, active circuit embeddings and PPO tensors to the
  selected device. Keep inactive circuits on CPU to avoid filling GPU memory.
  Move optimizer state correctly on resume. Treat hardware selection as runtime
  configuration, allowing old CPU checkpoints to be tested on GPU.
- Keep DeepGate2 weights frozen; support selected-device feature extraction,
  device-specific model caching, CPU export arrays and accurate device provenance.
  Existing valid feature caches remain reusable. Restore caller RNG and thread
  settings after extraction.
- Preserve network architecture, dynamic context, complete remaining-fault
  scoring, Primary tie-breaking, BFS candidate membership, and FAN coverage
  checks. DTC continues to reuse the current step's scores.
- Avoid per-fault GPU synchronization in policy bookkeeping: copy step scores
  to CPU once for deterministic selection, DTC callbacks and evaluation-only
  probability/entropy statistics. Training replay remains differentiable on GPU.
- Bound evaluation scoring memory with chunks sharing the same complete-set
  context. Chunking must preserve critic aggregation and fault-score ordering
  within normal floating-point tolerances; it must not sample a fault subset.
- FAN remains a CPU solver. CPU tensor threads do not imply parallelizing a
  single stateful FAN session or sharing it across threads.
- Preserve CPU checkpoint loading and add CUDA RNG capture/restoration, while
  accepting old checkpoints without CUDA RNG state. Same-device deterministic
  continuation is the target; CPU and GPU need not produce bitwise equal runs.
- Add separate timing for feature construction, policy forward, FAN steps,
  policy bookkeeping and STC so the remaining bottleneck is visible.

## Alternatives considered

1. CUDA plus configurable CPU threads (selected): directly accelerates neural
   computation and retains the current fault-selection algorithm.
2. CPU threads only: smaller change, but does not satisfy the requested GPU use.
3. Parallel circuit workers: can improve throughput but duplicates solver/model
   memory and changes rollout coordination; defer from this change.

## Validation

Run existing policy, PPO, checkpoint, progress and CLI tests; add tests for
device resolution, old-checkpoint compatibility, CLI propagation, chunked
scoring parity and CPU resume. CUDA tests cover policy forward/backward,
optimizer resume and feature extraction when matching CUDA dependencies exist.
Report skipped hardware tests explicitly. Update Linux installation guidance
using official PyTorch/PyG compatibility sources; CPU-only PyTorch cannot use GPU.

## Acceptance

A Linux CUDA installation can run the existing train/test scripts with
`DEVICE=cuda THREADS=8`, startup confirms CUDA, and outputs preserve coverage
invariants. Validation found a CUDA-capable project environment on this Windows
machine (Python 3.9, PyTorch 1.11.0+cu115, GTX 1660 Ti), allowing real GPU tests.
Linux end-to-end speed still requires measurement on the target hardware.

## Implementation decisions

- New runs and testing default to at most 8 CPU threads. Resume preserves the
  saved thread count unless explicitly overridden, avoiding an unintended
  reduction-order change during continuation.
- `FEATURE_DEVICE=cpu` / `--feature-device cpu` allows CPU feature extraction with
  GPU policy computation. GPU DeepGate graph reductions can be nondeterministic;
  this is recorded in provenance and CUDA extraction enables PyTorch warnings
  for unavailable deterministic kernels. Caller deterministic settings are restored.
