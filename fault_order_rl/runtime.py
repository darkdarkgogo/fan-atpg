"""Explicit neural compute devices and CPU tensor thread controls."""

import os
import re

import torch

from .progress import progress


def default_threads():
    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = os.cpu_count() or 1
    return max(1, min(8, count))


def resolve_device(requested="auto"):
    requested = str(requested)
    if requested != "auto" and not re.fullmatch(r"cpu|cuda(?::[0-9]+)?", requested):
        raise ValueError("device must be auto, cpu, cuda or cuda:N")
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested.startswith("cuda"):
        # Required by deterministic cuBLAS on CUDA >= 10.2, before first GEMM.
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        if not torch.cuda.is_available():
            raise ValueError("CUDA requested but unavailable; install CUDA-enabled PyTorch and check the NVIDIA driver")
        index = torch.cuda.current_device() if requested == "cuda" else int(requested.split(":")[1])
        if index >= torch.cuda.device_count():
            raise ValueError("CUDA device index is out of range: " + requested)
        return torch.device("cuda", index)
    return torch.device("cpu")


def configure_runtime(device="auto", threads=None):
    count = default_threads() if threads is None else threads
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("threads must be a positive integer")
    selected = resolve_device(device)
    torch.set_num_threads(count)
    progress("RUNTIME", "configured", device=selected, threads=count,
             gpu=torch.cuda.get_device_name(selected) if selected.type == "cuda" else "none",
             requested=device, torch_version=torch.__version__)
    return selected


def synchronize(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def same_torch_release(saved):
    """CPU and CUDA wheels of the same release can share checkpoints."""
    return str(saved).split("+")[0] == str(torch.__version__).split("+")[0]
