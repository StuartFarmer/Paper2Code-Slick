import pytest

from codes.contracts import Limits, RunManifest
from codes.store import BudgetExceeded, RunStore


def manifest():
    return RunManifest(
        run_id="test-run",
        input_hashes={"prompts": "abc"},
        image_id="sha256:image",
        platform="linux/arm64",
        models={"worker": "openai/gpt-oss-120b:nitro"},
        output_repo="unused",
        limits=Limits(max_calls=2, run_timeout=3600),
    )


def test_lock_collision_immutable_artifacts_and_integrity(tmp_path):
    root = tmp_path / "run"
    with RunStore.create(root, manifest()) as store:
        with pytest.raises(FileExistsError):
            RunStore.create(root, manifest())
        with pytest.raises(RuntimeError, match="locked"):
            RunStore.open(root)
        artifact = store.save_artifact("source/paper.txt", "evidence")
        assert store.read_artifact(artifact) == "evidence"
        store.save_artifact("generated/manifest.json", "{}")
        with pytest.raises(ValueError, match="Reserved"):
            store.save_artifact("manifest.json", "{}")
        with pytest.raises(FileExistsError):
            store.save_artifact(artifact, "replacement")
        with pytest.raises(ValueError):
            store.save_artifact("../escape", "bad")
    (root / artifact).write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        RunStore.open(root)


def test_resume_preserves_unknown_calls(tmp_path):
    root = tmp_path / "run"
    with RunStore.create(root, manifest()) as store:
        first = store.reserve_call("worker", "a")
        store.save_artifact("candidates/orphan.py", "print('not accepted')")
    with RunStore.open(root, expected_hashes={"prompts": "abc"}) as store:
        assert store.manifest.calls_reserved == 1
        second = store.reserve_call("worker", "a")
        assert first != second
        with pytest.raises(BudgetExceeded):
            store.reserve_call("worker", "a")
    with pytest.raises(ValueError, match="inputs"):
        RunStore.open(root, expected_hashes={"prompts": "changed"})


def test_time_budget_survives_resume_and_excludes_clean_pause(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("codes.store.time.time", lambda: clock[0])
    root = tmp_path / "run"
    with RunStore.create(root, manifest()) as store:
        clock[0] += 10
        store.check_budget()
    clock[0] += 100000
    with RunStore.open(root) as store:
        assert store.manifest.active_seconds == 10
        clock[0] += 3591
        with pytest.raises(BudgetExceeded):
            store.check_budget()


def test_identical_artifact_recovers_crash_before_inventory(tmp_path):
    with RunStore.create(tmp_path / "run", manifest()) as store:
        (store.root / "evidence.txt").write_text("original")
        store.save_artifact("evidence.txt", "original")
        assert store.read_artifact("evidence.txt") == "original"
        with pytest.raises(FileExistsError):
            store.save_artifact("evidence.txt", "changed")
