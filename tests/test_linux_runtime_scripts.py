"""Exercise shell argument propagation without starting an ATPG run."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("mode", ["test", "train", "resume", "prepare"])
def test_linux_scripts_forward_compute_controls(tmp_path, mode):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash unavailable")
    root = Path(__file__).resolve().parents[1]
    stub = tmp_path / "record-python"
    stub.write_bytes(b"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n")
    stub.chmod(0o755)
    env = dict(os.environ, PYTHON=stub.as_posix(), DEVICE="cuda:1", THREADS="6",
               FEATURE_DEVICE="cpu", INFERENCE_CHUNK_SIZE="4096")
    output = tmp_path / "run"
    if mode == "test":
        script = root / "scripts/test_fan_linux.sh"
        args = ["saved.pt", "input_v", str(output), "cells.mdt"]
    elif mode in ("train", "resume"):
        script = root / "scripts/train_fan_linux.sh"
        args = [str(output), "2", "custom.json"]
        if mode == "resume":
            output.mkdir()
            (output / "latest.pt").touch()
    else:
        script = root / "scripts/prepare_fan_linux.sh"
        args = ["custom.json"]
    completed = subprocess.run([bash, str(script), *args], env=env, cwd=root,
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    received = completed.stdout.splitlines()
    def value(flag):
        return received[received.index(flag) + 1]
    assert value("--threads") == "6"
    assert value("--device") == ("cpu" if mode == "prepare" else "cuda:1")
    if mode != "prepare":
        assert value("--inference-chunk-size") == "4096"
    if mode == "test":
        assert value("--feature-device") == "cpu"
        assert value("--checkpoint") == "saved.pt"
        assert value("--test-dir") == "input_v"
    if mode == "resume":
        assert value("--resume").replace("\\", "/").endswith("/run/latest.pt")
