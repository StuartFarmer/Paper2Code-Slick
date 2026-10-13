import asyncio
import json

import pytest

from codes.contracts import CheckSpec
from codes.execution import docker_argv, materialize_snapshot, parse_report, run_check


def test_snapshot_rejects_unsafe_generated_paths(tmp_path):
    for i, path in enumerate(["../escape.py", ".git/config", "/tmp/escape.py"]):
        with pytest.raises(ValueError):
            materialize_snapshot(tmp_path / str(i), {path: "x"})
    assert not (tmp_path / "escape.py").exists()


def test_fixed_container_controls_and_spaced_paths(tmp_path):
    check = CheckSpec(id="c", kind="pytest", targets=["tests/acceptance/a/test_a.py::test_a"])
    args = docker_argv(
        check, tmp_path / "space here", tmp_path / "suite", "sha256:test", "p2c-test"
    )
    assert "--read-only" in args and args[args.index("--network") + 1] == "none"
    assert "--rm" not in args and "--env-file" not in args
    assert any("space here" in value for value in args)
    assert not any("OPENROUTER" in value for value in args)


@pytest.mark.parametrize(
    "report",
    [
        "",
        "P2C_RESULT={",
        'P2C_RESULT={"exit_code":0}',
        'P2C_RESULT={"exit_code":0,"collected":[],"passed":[],"failed":[],"skipped":[],"errors":[]}',
    ],
)
def test_missing_forged_and_zero_collection_reports_fail(report):
    check = CheckSpec(id="c", kind="pytest", targets=["tests/acceptance/a/test_a.py::test_a"])
    with pytest.raises(ValueError):
        parse_report(report, check)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {
            "kind": "syntax",
            "targets": ["a.py"],
            "exit_code": "0",
            "collected": [],
            "passed": [],
            "failed": [],
            "skipped": [],
            "errors": [],
        },
    ],
)
def test_malformed_report_types_fail_closed(payload):
    check = CheckSpec(id="c", kind="syntax", targets=["a.py"])
    with pytest.raises(ValueError):
        parse_report("P2C_RESULT=" + json.dumps(payload), check)


def test_fake_docker_inspects_before_removal(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "argv.jsonl"
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/usr/bin/env python3\nimport sys,json\nfrom pathlib import Path\n"
        + f"with Path({str(log)!r}).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        + "if sys.argv[1]=='run': print('P2C_RESULT='+json.dumps({'kind':'syntax','targets':['a.py'],'exit_code':0,'collected':[],'passed':[],'failed':[],'skipped':[],'errors':[]}))\n"
        + "if sys.argv[1]=='inspect': print(json.dumps({'OOMKilled':False,'ExitCode':0}))\n"
    )
    fake.chmod(0o755)
    import os

    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    workspace, suite = tmp_path / "work", tmp_path / "suite"
    workspace.mkdir()
    suite.mkdir()
    (workspace / "a.py").write_text("x=1")
    result = asyncio.run(
        run_check(
            CheckSpec(id="syntax", kind="syntax", targets=["a.py"]), workspace, suite, "sha256:test"
        )
    )
    assert result.status == "passed"
    commands = [json.loads(line)[0] for line in log.read_text().splitlines()]
    assert commands == ["run", "inspect", "rm"]


def test_snapshot_publication_is_atomic_on_write_failure(tmp_path, monkeypatch):
    from pathlib import Path

    from codes.execution import materialize_snapshot

    original = Path.write_text

    def fail(path, *args, **kwargs):
        if path.name == "b.py":
            raise OSError("disk failure")
        return original(path, *args, **kwargs)

    root = tmp_path / "snapshot"
    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", fail)
        with pytest.raises(OSError):
            materialize_snapshot(root, {"a.py": "x=1", "b.py": "x=2"})
    assert not root.exists()
    materialize_snapshot(root, {"a.py": "x=1", "b.py": "x=2"})
    assert (root / "b.py").read_text() == "x=2"


def test_cleanup_targets_only_the_locked_run(monkeypatch):
    import subprocess

    from codes.execution import cleanup_run

    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "p2c-orphan\n" if "ps" in argv else "", "")

    monkeypatch.setattr(subprocess, "run", command)
    cleanup_run("run123")
    assert "label=paper2code.run=run123" in calls[0]
    assert "label=paper2code.executor=true" in calls[0]
    assert calls[1] == ["docker", "rm", "--force", "p2c-orphan"]


def test_cancellation_waits_for_container_removal(tmp_path, monkeypatch):
    import asyncio

    from codes.contracts import CheckSpec
    from codes.execution import run_check

    async def exercise():
        removing, release, removed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Process:
            def __init__(self, kind):
                self.kind = kind
                self.returncode = 0
                self.stdout = asyncio.StreamReader()
                self.stdout.feed_eof()
                self.stderr = asyncio.StreamReader()
                self.stderr.feed_eof()

            async def wait(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

            async def communicate(self):
                if self.kind == "rm":
                    removing.set()
                    await release.wait()
                    removed.set()
                return (b"{}", b"")

        async def start(*args, **kwargs):
            return Process(args[1])

        monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
        work = tmp_path / "work"
        work.mkdir()
        (work / "a.py").write_text("x=1")
        suite = tmp_path / "suite"
        suite.mkdir()
        task = asyncio.create_task(
            run_check(
                CheckSpec(id="syntax", kind="syntax", targets=["a.py"]), work, suite, "sha256:test"
            )
        )
        await asyncio.wait_for(removing.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        returned_before_removal = task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(removed.wait(), 1)
        assert not returned_before_removal
        assert len(list((tmp_path / "checks").glob("*/result.json"))) == 1

    asyncio.run(exercise())


def test_published_snapshot_is_readable_by_executor_under_private_umask(tmp_path):
    import os
    import stat

    from codes.execution import materialize_snapshot

    root = tmp_path / "snapshot"
    previous = os.umask(0o077)
    try:
        materialize_snapshot(root, {"pkg/a.py": "x=1\n"})
    finally:
        os.umask(previous)
    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "pkg").stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "pkg/a.py").stat().st_mode) == 0o644
