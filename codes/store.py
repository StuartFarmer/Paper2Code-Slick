"""Locked run state, immutable evidence, and crash-conservative budgets."""

import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from .contracts import CallRecord, RunManifest, TaskRecord
from .workflow import output_path


class BudgetExceeded(RuntimeError):
    pass


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_write(path: Path, content: str, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class RunStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = (self.root / "run.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.lock.close()
            raise RuntimeError(f"Run is locked: {root}") from error

    @classmethod
    def create(cls, root: Path, manifest: RunManifest):
        root.mkdir(parents=True, exist_ok=False)
        store = cls(root)
        store.manifest = manifest.model_copy(deep=True)
        store.artifacts = {}
        store.manifest.active_since = time.time()
        try:
            store.save_manifest()
            atomic_write(store.root / "artifacts.json", "{}\n")
        except BaseException:
            store.lock.close()
            raise
        return store

    @classmethod
    def open(cls, root: Path, *, expected_hashes: dict[str, str] | None = None):
        store = cls(root)
        try:
            store.manifest = RunManifest.model_validate_json(
                (store.root / "manifest.json").read_text()
            )
            if expected_hashes is not None and expected_hashes != store.manifest.input_hashes:
                raise ValueError("Run inputs changed; create a new run")
            store.artifacts = json.loads((store.root / "artifacts.json").read_text())
            for name, expected in store.artifacts.items():
                if digest(output_path(store.root, name).read_bytes()) != expected:
                    raise ValueError(f"Artifact hash mismatch: {name}")
            # Unobserved time after a crash is conservatively active; clean pauses are free.
            store._charge_elapsed()
            store.manifest.active_since = time.time()
            store.save_manifest()
        except BaseException:
            store.lock.close()
            raise
        return store

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _charge_elapsed(self) -> None:
        now = time.time()
        if self.manifest.active_since is not None:
            self.manifest.active_seconds += max(0, now - self.manifest.active_since)
        self.manifest.active_since = now

    def save_manifest(self) -> None:
        atomic_write(self.root / "manifest.json", self.manifest.model_dump_json(indent=2) + "\n")

    def close(self) -> None:
        if not self.lock.closed:
            try:
                self._charge_elapsed()
                self.manifest.active_since = None
                self.save_manifest()
            finally:
                self.lock.close()

    def check_budget(self) -> None:
        self._charge_elapsed()
        self.save_manifest()
        if self.manifest.active_seconds >= self.manifest.limits.run_timeout:
            raise BudgetExceeded("Active run time budget exhausted")

    def reserve_call(self, role: str, task_id: str) -> str:
        self.check_budget()
        if self.manifest.calls_reserved >= self.manifest.limits.max_calls:
            raise BudgetExceeded("Model call budget exhausted")
        self.manifest.calls_reserved += 1
        self.save_manifest()
        call_id = f"call-{self.manifest.calls_reserved:05d}"
        call = CallRecord(
            id=call_id,
            role=role,
            model=self.manifest.models.get(role, ""),
            task_id=task_id,
            attempt=self.manifest.calls_reserved,
            started=time.time(),
        )
        self.save_artifact(f"calls/{call_id}/reservation.json", call.model_dump_json(indent=2))
        return call_id

    def save_artifact(self, relative_path: str, content: str) -> str:
        path = output_path(self.root, relative_path)
        if path.name in {
            "manifest.json",
            "artifacts.json",
            "state.json",
            "run.lock",
            "events.jsonl",
        }:
            raise ValueError("Reserved controller state path")
        atomic_write(path, content, immutable=True)
        self.artifacts[relative_path] = digest(content.encode("utf-8"))
        atomic_write(
            self.root / "artifacts.json", json.dumps(self.artifacts, sort_keys=True) + "\n"
        )
        return relative_path

    def read_artifact(self, name: str) -> str:
        expected = self.artifacts[name]
        content = output_path(self.root, name).read_bytes()
        if digest(content) != expected:
            raise ValueError(f"Artifact hash mismatch: {name}")
        return content.decode("utf-8")

    def save_task(self, record: TaskRecord) -> None:
        if "/" in record.task_id:
            raise ValueError("Task ID cannot contain directories")
        path = output_path(self.root, f"tasks/{record.task_id}/state.json")
        atomic_write(path, record.model_dump_json(indent=2) + "\n")
        self.event("task_state", task=record.task_id, state=record.state)

    def load_task(self, task_id: str) -> TaskRecord:
        return TaskRecord.model_validate_json(
            output_path(self.root, f"tasks/{task_id}/state.json").read_text()
        )

    def event(self, kind: str, **fields) -> None:
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": kind, "time": time.time(), **fields}) + "\n")
