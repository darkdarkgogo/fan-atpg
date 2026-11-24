"""Device routing, bounded inference, and portable schema-10 checkpoints."""

import copy
from types import SimpleNamespace

import pytest
import torch

from fault_order_rl.checkpoint import capture_rng, restore_rng, load_checkpoint, save_checkpoint
from fault_order_rl.model import FaultActorCritic, build_dynamic_features, score_remaining
from fault_order_rl.runtime import configure_runtime, resolve_device, same_torch_release
from fault_order_rl.trainer import TrainConfig, Trainer, evaluate_checkpoint


@pytest.fixture(autouse=True)
def preserve_runtime():
    state = capture_rng()
    threads = torch.get_num_threads()
    deterministic = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    yield
    restore_rng(state)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic, warn_only=warn_only)


def test_device_resolution_fails_explicitly_without_cuda(monkeypatch, capsys):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert configure_runtime("auto", 2) == torch.device("cpu")
    assert torch.get_num_threads() == 2
    assert "device=cpu threads=2" in capsys.readouterr().err
    with pytest.raises(ValueError, match="CUDA requested but unavailable"):
        resolve_device("cuda")
    for name in ("bad", "cuda:-1", "cpu:1"):
        with pytest.raises(ValueError, match="device must"):
            resolve_device(name)
    with pytest.raises(ValueError, match="threads"):
        configure_runtime("cpu", 0)


def test_explicit_cuda_index_validation(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "current_device", lambda: 1)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 2)
    assert resolve_device("auto") == torch.device("cuda:1")
    assert resolve_device("cuda:0") == torch.device("cuda:0")
    with pytest.raises(ValueError, match="out of range"):
        resolve_device("cuda:2")


def test_torch_cpu_cuda_builds_share_release(monkeypatch):
    monkeypatch.setattr(torch, "__version__", "2.5.1+cu121")
    assert same_torch_release("2.5.1+cpu")
    assert same_torch_release("2.5.1")
    assert not same_torch_release("2.5.0+cpu")


@pytest.mark.parametrize("device", ["cpu", pytest.param("cuda", marks=pytest.mark.skipif(
    not torch.cuda.is_available(), reason="CUDA hardware/runtime unavailable"))])
def test_chunked_scores_use_complete_context_and_critic_mean(device):
    selected = resolve_device(device)
    torch.manual_seed(23)
    model = FaultActorCritic().to(selected).eval()
    embeddings = torch.randn(71, 257, device=selected)
    rows = tuple(range(69, 2, -2))
    with torch.no_grad():
        expected_scores, expected_value = model(build_dynamic_features(embeddings, rows))
    timing = {}
    actual_scores, actual_value = score_remaining(model, embeddings, rows, 7, timing)
    torch.testing.assert_close(actual_scores, expected_scores, rtol=1e-4, atol=1e-6)
    torch.testing.assert_close(actual_value, expected_value, rtol=1e-4, atol=1e-6)
    assert actual_scores.device == expected_scores.device
    assert not actual_scores.requires_grad
    assert timing["features_s"] >= 0 and timing["forward_s"] >= 0
    # Tied scores retain the stable global catalog-row tie break.
    with torch.no_grad():
        model.actor_head.weight.zero_()
        model.actor_head.bias.zero_()
    scores, _ = score_remaining(model, embeddings, rows, 7)
    from fault_order_rl.policy import sample_primary
    assert int(sample_primary(scores.cpu(), rows, 1.0, False)) == min(rows)


def test_cpu_structure_initializer_adapter_keeps_original_inputs():
    from fault_embedding.inference import _cpu_structure_init
    graph = SimpleNamespace(batch=None, forward_level=torch.tensor([0, 0, 1]),
                            forward_index=torch.arange(3))
    called = []

    def original(metadata, hs, dimension):
        called.append(metadata)
        assert hs.device.type == "cpu" and dimension == 128
        assert metadata.batch is None
        assert torch.equal(metadata.forward_level, graph.forward_level)
        assert torch.equal(metadata.forward_index, graph.forward_index)
        return hs + 1

    result = _cpu_structure_init(original)(graph, torch.zeros(3, 128), 128)
    assert torch.equal(result, torch.ones(3, 128))
    assert len(called) == 1


def test_legacy_rng_without_cuda_state_is_accepted():
    state = capture_rng()
    state.pop("cuda", None)
    expected = torch.rand(3)
    restore_rng(state)
    assert torch.equal(torch.rand(3), expected)


@pytest.mark.parametrize("device", ["cpu", pytest.param("cuda", marks=pytest.mark.skipif(
    not torch.cuda.is_available(), reason="CUDA hardware/runtime unavailable"))])
def test_old_cpu_checkpoint_resume_optimizer_and_test_on_selected_device(tmp_path, monkeypatch, device):
    from test_fault_order_rl import _circuit, _manifest, _FakeEnvironment, _RecordingWriter
    from fault_order_rl import trainer as trainer_module

    circuit = _circuit(tmp_path, "device_test", "fixed-digest", count=3)
    manifest = _manifest(tmp_path / "manifest.json", [circuit.name])
    environment = _FakeEnvironment([circuit])
    monkeypatch.setattr(trainer_module, "load_all_circuits", lambda manifest, env: env.circuits)
    monkeypatch.setattr(trainer_module, "_create_summary_writer", lambda path: _RecordingWriter())
    output = tmp_path / "run"
    cpu = Trainer.create(manifest, TrainConfig(rounds=2, device="cpu", threads=2), output, environment)
    cpu.step()  # Populate Adam state before exercising CPU -> CUDA loading.
    saved = load_checkpoint(output / "latest.pt")
    saved["config"].pop("device")
    saved["config"].pop("inference_chunk_size")
    saved["rng"].pop("cuda", None)
    saved["torch_version"] = str(torch.__version__).split("+")[0] + "+cpu"
    save_checkpoint(output / "latest.pt", saved)
    default_resume = Trainer.resume(output / "latest.pt", environment=environment, device="cpu")
    assert default_resume.config.threads == 2
    resumed = Trainer.resume(output / "latest.pt", environment=environment,
                             device=device, threads=2, inference_chunk_size=2)
    assert next(resumed.model.parameters()).device.type == device
    for parameter, state in resumed.optimizer.state.items():
        assert state["exp_avg"].device == parameter.device
        assert state["exp_avg_sq"].device == parameter.device
    before = copy.deepcopy(resumed.model.state_dict())
    resumed.train()
    assert any(not torch.equal(value, resumed.model.state_dict()[key]) for key, value in before.items())
    assert circuit.embeddings.device.type == "cpu"  # Dataset remains off GPU.
    report = evaluate_checkpoint(output / "final.pt", tmp_path / "evaluation",
                                 environment=environment, manifest=manifest,
                                 device=device, threads=2, inference_chunk_size=2)
    assert report["coverage_eligible"]
    assert (tmp_path / "evaluation" / "summary.json").is_file()


def test_test_cli_passes_runtime_to_features_and_evaluation(tmp_path, monkeypatch):
    from fault_order_rl import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, "configure_runtime", lambda *args: calls.append(("runtime", args)))
    monkeypatch.setattr(cli, "prepare_test_features", lambda manifest, **kw: calls.append(("features", kw)))
    monkeypatch.setattr(cli, "evaluate_checkpoint", lambda *args, **kw: calls.append(("test", kw)) or {})
    monkeypatch.setattr(cli, "_print_evaluation_by_circuit", lambda report: None)
    assert cli.main(["test", "--checkpoint", str(tmp_path / "final.pt"),
                     "--manifest", str(tmp_path / "test.json"), "--device", "cuda:1",
                     "--threads", "6", "--feature-device", "cpu", "--inference-chunk-size", "1000"]) == 0
    assert calls[0] == ("runtime", ("cuda:1", 6))
    assert calls[1] == ("features", {"device": "cpu", "threads": 6})
    assert calls[2][1]["device"] == "cuda:1"
    assert calls[2][1]["threads"] == 6
    assert calls[2][1]["inference_chunk_size"] == 1000


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA hardware/runtime unavailable")
def test_deepgate_cuda_extraction_restores_rng_and_threads():
    pytest.importorskip("torch_geometric")
    from test_pretrained_fault_embeddings import _tiny_graph
    from fault_embedding.inference import infer_gate_embeddings
    state = capture_rng()
    threads = torch.get_num_threads()
    arrays, provenance = infer_gate_embeddings(_tiny_graph(), device="cuda", threads=2)
    assert provenance["device"].startswith("cuda:")
    assert arrays["hf"].shape[1] == 128
    assert torch.get_num_threads() == threads
    assert torch.equal(torch.get_rng_state(), state["torch"])
    assert all(torch.equal(a, b) for a, b in zip(torch.cuda.get_rng_state_all(), state["cuda"]))


@pytest.mark.parametrize("device", ["cpu", pytest.param("cuda", marks=pytest.mark.skipif(
    not torch.cuda.is_available(), reason="CUDA hardware/runtime unavailable"))])
def test_real_fan_policy_and_deepgate_export_preserve_independent_coverage(tmp_path, device):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "FAN_ATPG"))
    pytest.importorskip("cpp_fan")
    pytest.importorskip("torch_geometric")
    from fault_order_rl.data import CircuitSpec, load_circuit_data
    from fault_order_rl.environment import FanEnvironment
    from scripts.prepare_fan_data import export
    from validation.independent_sim import coverage

    netlist = tmp_path / "tiny.v"
    netlist.write_text("module top(a,b,c,z); input a,b,c; output z; wire n,m; "
                       "FAN_AND2 u0 (.A0(a),.A1(b),.Z(n)); "
                       "FAN_XOR2 u1 (.A0(n),.A1(c),.Z(m)); "
                       "FAN_OR2 u2 (.A0(m),.A1(a),.Z(z)); endmodule")
    target = tmp_path / "features"
    spec = CircuitSpec(name="tiny", netlist_path=netlist,
                       library_path=root / "datasets/verilog/fan_primitives.mdt",
                       graph_path=target / "tiny.graph.json",
                       metadata_path=target / "tiny.faults.json",
                       embeddings_path=target / "tiny.fault_embeddings.npz")
    environment = FanEnvironment(root / "FAN_ATPG")
    graph = environment.circuit_graph(netlist, spec.library_path)
    catalog = environment.catalog(netlist, spec.library_path)
    selected = configure_runtime(device, 2)
    export(spec, catalog, graph, device=device, threads=2)
    circuit = load_circuit_data(spec, catalog, graph)
    trainer = Trainer.__new__(Trainer)
    trainer.config = TrainConfig(device=device, threads=2, inference_chunk_size=2)
    trainer.environment = environment
    baseline, _ = trainer._run_native(circuit, environment)
    model = FaultActorCritic().to(selected).eval()
    result, _, decisions, _ = trainer._run_policy(circuit, model, 1.0, False)
    actual = coverage(graph, result["test_vectors"], result["input_names"])
    assert actual["detected"] == result["detected_equivalent_faults"]
    assert result["covered_equivalent_faults"] == baseline["covered_equivalent_faults"]
    assert result["stc_coverage_preserved"]
    assert decisions
