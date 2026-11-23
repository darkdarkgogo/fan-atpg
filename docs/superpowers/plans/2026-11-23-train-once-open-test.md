# Train once and open test set implementation plan

**Goal:** Training performs one pass without model evaluation/selection; testing discovers arbitrary compatible netlists independently.

**Architecture:** Keep PPO rollout/reward machinery, detach test data from Trainer lifecycle/checkpoints, retain explicit native-versus-policy comparison only in a standalone test command.

**Spec:** `docs/superpowers/specs/2026-11-23-train-once-open-test-design.md`

1. Inspect trainer/checkpoint/tests and add tests for no-evaluation final publication and extensible test discovery.
2. Remove automatic validation/best from create/resume/train round/final and checkpoint payload. Update CLI and Linux/PowerShell entrypoints to training-only defaults.
3. Add test directory discovery and independent final/latest testing with no circuit whitelist; generate new circuit artifacts on demand. Rewrite regression tests around the new lifecycle.
4. Synthesize pinned b14/b17/b18/b19, combine with existing b12/b15/b20/b21/b22 under the open test directory, record hashes and native compatibility checks. Test name/count checks are structural only.
5. Preserve embedded repository Git histories under tmp, convert both gitlinks to regular tracked source directories, and check untracked runtime dependencies and generated parser snapshots.
6. Run relevant and full tests, review independently, update README/Linux instructions and recreate the transfer archive. No full 1024-circuit training run or remote push is performed as part of this implementation.
