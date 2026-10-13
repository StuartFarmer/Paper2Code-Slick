import asyncio
import json

import pytest
from test_contracts import spec_plan

from codes.contracts import Candidate, CheckSpec
from codes.execution import docker_argv, parse_report, run_check, stage_candidate


def test_candidate_requires_exact_owned_files_and_confined_paths(tmp_path):
    _, plan = spec_plan()
    task = plan.tasks[0]
    for path in ["../escape.py", ".git/config", "b.py"]:
        with pytest.raises(ValueError):
            stage_candidate(
                task,
                Candidate(kind="candidate", files=[{"path": path, "content": "x"}], notes=""),
                tmp_path / "bad",
            )
    candidate = Candidate(kind="candidate", files=[{"path": "a.py", "content": "x=1\n"}], notes="")
    sha = stage_candidate(task, candidate, tmp_path / "snapshot")
    assert len(sha) == 64 and (tmp_path / "snapshot/a.py").read_text() == "x=1\n"
    with pytest.raises(FileExistsError):
        stage_candidate(task, candidate, tmp_path / "snapshot")
    candidate.files[0].content = "λ" * 9000
    with pytest.raises(ValueError):
        stage_candidate(task, candidate, tmp_path / "large")


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
