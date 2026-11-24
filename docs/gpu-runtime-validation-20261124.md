# GPU runtime validation, 2026-11-24

Validated on Windows with the project's Python 3.9 d2l environment,
PyTorch 1.11.0+cu115, PyG 2.1.0, and NVIDIA GeForce GTX 1660 Ti.
The default Python 3.13 environment has CPU-only PyTorch 2.14.0.

Checks cover CPU/CUDA device selection, explicit unavailable-device errors,
global-context chunked inference and critic parity, CUDA PPO forward/backward,
CPU-checkpoint Adam state migration to GPU, final-checkpoint evaluation,
legacy schema-10 config/RNG compatibility, CPU thread preservation on resume,
actual pinned DeepGate2 CUDA extraction and RNG/thread restoration, and real
FAN ATPG/STC with independent fault-coverage verification on CPU and CUDA.
Shell tests execute the Linux wrappers using Bash with a recording Python stub,
checking new-training, resume, testing, and feature-preparation argument forwarding.

Full validation command (use an unused temporary directory):

```powershell
& C:/Users/acer/.conda/envs/d2l/python.exe -m pytest -o addopts= -q --basetemp=.tmp-gpu-tests-final -p no:cacheprovider
```

Final result: **179 passed**, 5 warnings, 37.33 seconds. No skipped CUDA tests.
The warnings are the CUDA scatter-add determinism warning described below.

PyTorch emits a known warning that DeepGate's CUDA scatter-add reduction lacks
a deterministic implementation. CUDA feature extraction uses warn-only mode;
strict CPU extraction remains available. GPU and CPU results are not promised
to be bitwise identical. The real FAN integration test checks coverage independently.

## Scoring microbenchmark

Untrained identical FaultActorCritic weights, 100,000 random 257-dimensional
fault embeddings, complete remaining set, scoring chunks of 16,384 rows.
One warmup, then median of three timed runs, including context construction,
network inference and output-score transfer to CPU. Initial model/embedding
transfer is excluded because embeddings remain on the active device per episode.

| Compute | CPU threads | Median seconds |
| --- | ---: | ---: |
| CPU | 1 | 1.3775 |
| CPU | 8 | 0.6012 |
| CUDA / GTX 1660 Ti | 8 | 0.04168 |

The maximum absolute score difference relative to CPU single-thread scoring
was 0 for CPU 8-thread scoring and 2.98e-7 for CUDA. This measures the neural
scoring path only, not a complete ATPG episode, graph preparation, STC or export.
Target Linux runtime and full-circuit speedup have not been measured here.

Independent review found a resume-thread override issue, which was fixed by
preserving saved threads unless explicitly overridden. No significant findings
remained after review.
