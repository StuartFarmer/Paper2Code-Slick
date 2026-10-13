import json

import pytest

from codes.contracts import Limits, RunManifest, TaskRecord
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
        with pytest.raises(FileExistsError):
            store.save_artifact(artifact, "replacement")
        with pytest.raises(ValueError):
            store.save_artifact("../escape", "bad")
    (root / artifact).write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        RunStore.open(root)


def test_resume_preserves_unknown_calls_and_task_state(tmp_path):
    root = tmp_path / "run"
    with RunStore.create(root, manifest()) as store:
        first = store.reserve_call("worker", "a")
        store.save_task(TaskRecord(task_id="a", plan_hash="p", state="pending"))
        store.save_artifact("candidates/orphan.py", "print('not accepted')")
    with (root / "events.jsonl").open("a") as stream:
        stream.write('{"partial":')
    with RunStore.open(root, expected_hashes={"prompts": "abc"}) as store:
        assert store.manifest.calls_reserved == 1
        assert store.load_task("a").state == "pending"
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


def test_failed_state_publication_preserves_old_authoritative_state(tmp_path, monkeypatch):
    root = tmp_path / "run"
    with RunStore.create(root, manifest()) as store:
        store.save_task(TaskRecord(task_id="a", plan_hash="p", state="pending"))

        def crash(*args):
            raise OSError("simulated crash before rename")

        with monkeypatch.context() as patch:
            patch.setattr("codes.store.os.replace", crash)
            with pytest.raises(OSError):
                store.save_task(TaskRecord(task_id="a", plan_hash="p", state="checking"))
        assert store.load_task("a").state == "pending"
    state = json.loads((root / "tasks/a/state.json").read_text())
    assert state["state"] == "pending"


def test_crash_after_commit_does_not_erase_state(tmp_path, monkeypatch):
    with RunStore.create(tmp_path / "run", manifest()) as store:

        def fail_journal(*args, **kwargs):
            raise OSError("journal write failed after transaction")

        monkeypatch.setattr(store, "event", fail_journal)
        with pytest.raises(OSError):
            store.save_task(TaskRecord(task_id="a", plan_hash="p", state="checking"))
        assert store.load_task("a").state == "checking"


def test_identical_artifact_recovers_crash_before_inventory(tmp_path):
    with RunStore.create(tmp_path / "run", manifest()) as store:
        (store.root / "evidence.txt").write_text("original")
        store.save_artifact("evidence.txt", "original")
        assert store.read_artifact("evidence.txt") == "original"
        with pytest.raises(FileExistsError):
            store.save_artifact("evidence.txt", "changed")
