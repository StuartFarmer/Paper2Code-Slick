"""Explicit opt-in integration checks; all fixture programs execute in Docker."""

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from codes.contracts import CheckSpec
from codes.execution import run_check

pytestmark = pytest.mark.skipif(
    not os.environ.get("P2C_TEST_IMAGE"),
    reason="Set P2C_TEST_IMAGE to the built image ID for required executor checks",
)


def staged(tmp_path, source="x=1\n", test="def test_ok():\n    assert True\n"):
    work, suite = tmp_path / "work", tmp_path / "suite"
    work.mkdir()
    (suite / "tests/acceptance/check").mkdir(parents=True)
    (work / "a.py").write_text(source)
    (suite / "tests/acceptance/check/test_a.py").write_text(test)
    return work, suite


def check(tmp_path, source="x=1\n", test="def test_ok():\n    assert True\n", timeout=20):
    work, suite = staged(tmp_path, source, test)
    spec = CheckSpec(
        id="test",
        kind="pytest",
        targets=["tests/acceptance/check/test_a.py::test_ok"],
        timeout_seconds=timeout,
    )
    return asyncio.run(run_check(spec, work, suite, os.environ["P2C_TEST_IMAGE"]))


def test_isolation_and_numeric_dependencies(tmp_path):
    test = """import os, socket
import pytest
from pathlib import Path
def test_ok():
    import numpy, pandas, scipy, yaml, torch
    assert torch.version.cuda is None
    assert os.getuid() != 0
    assert not any('API_KEY' in key for key in os.environ)
    for path in ['/workspace/a.py', '/acceptance/tests/acceptance/check/test_a.py', '/root-file']:
        with pytest.raises(OSError): Path(path).write_text('change')
    with pytest.raises(OSError): socket.create_connection(('1.1.1.1', 443), timeout=1)
    Path('/tmp/check').write_text('temporary')
"""
    result = check(tmp_path, test=test, timeout=60)
    assert result.status == "passed", (
        Path(result.stdout_artifact).read_text() + Path(result.stderr_artifact).read_text()
    )


@pytest.mark.parametrize(
    "test, expected",
    [
        ("def test_ok():\n    assert False\n", "failed"),
        ("def test_other(): pass\n", "infrastructure_error"),
        ("import nonexistent_dependency\ndef test_ok(): pass\n", "infrastructure_error"),
        ("import time\ndef test_ok(): time.sleep(100)\n", "timeout"),
        (
            "from hypothesis import given, strategies as st\n@given(st.integers(0,100))\ndef test_ok(x): assert x < 3\n",
            "failed",
        ),
        (
            "from hypothesis import given, strategies as st, assume\n@given(st.integers())\ndef test_ok(x): assume(False)\n",
            "failed",
        ),
        (
            "from hypothesis import given, strategies as st\n@given(st.sampled_from([1,2]))\ndef test_ok(x): assert x > 0\n",
            "passed",
        ),
    ],
)
def test_real_results(tmp_path, test, expected):
    result = check(tmp_path, test=test, timeout=4 if expected == "timeout" else 20)
    assert result.status == expected, Path(result.stdout_artifact).read_text()


def test_bounded_output_and_descendant_cleanup(tmp_path):
    test = "import os,subprocess\ndef test_ok():\n    subprocess.Popen(['python','-c','import time; time.sleep(100)'])\n    os.write(1,b'x'*2000000)\n    assert True\n"
    result = check(tmp_path, test=test)
    assert result.status == "passed"
    assert result.output_truncated
    assert Path(result.stdout_artifact).stat().st_size <= 1024 * 1024
    container = result.argv[result.argv.index("--name") + 1]
    assert (
        subprocess.run(
            ["docker", "inspect", container], capture_output=True, check=False
        ).returncode
        != 0
    )


def test_oom_and_cancellation_cleanup(tmp_path):
    result = check(
        tmp_path,
        test="def test_ok():\n    value=bytearray(3*1024**3)\n    assert value\n",
        timeout=30,
    )
    assert result.status == "oom"
    other = tmp_path / "cancel"
    other.mkdir()
    work, suite = staged(other, test="import time\ndef test_ok(): time.sleep(100)\n")

    async def cancel():
        task = asyncio.create_task(
            run_check(
                CheckSpec(
                    id="c", kind="pytest", targets=["tests/acceptance/check/test_a.py::test_ok"]
                ),
                work,
                suite,
                os.environ["P2C_TEST_IMAGE"],
            )
        )
        await asyncio.sleep(2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    result_paths = list((other / "checks").glob("*/result.json"))
    assert len(result_paths) == 1
    import json

    argv = json.loads(result_paths[0].read_text())["argv"]
    assert (
        subprocess.run(
            ["docker", "inspect", argv[argv.index("--name") + 1]], capture_output=True, check=False
        ).returncode
        != 0
    )


def test_property_statistics_and_profile_override(tmp_path):
    result = check(
        tmp_path,
        test="from hypothesis import given, strategies as st\n@given(st.integers(0,5))\ndef test_ok(x): assert x >= 0\n",
    )
    assert result.status == "passed"
    stats = result.property_statistics["tests/acceptance/check/test_a.py::test_ok"]
    assert "6 passing, 0 failing, and 0 invalid test cases" in stats["summary"]
    changed = tmp_path / "override"
    changed.mkdir()
    result = check(
        changed,
        test="from hypothesis import given, strategies as st, settings\n@settings(max_examples=1)\n@given(st.integers())\ndef test_ok(x): pass\n",
    )
    assert result.status != "passed"


def test_complete_workflow_uses_real_execution(tmp_path, monkeypatch):
    import json

    from providers import ScriptedProvider
    from slick import prompts
    from test_simple_workflow import case

    from codes.agent import PaperCoder, run_workflow
    from codes.store import RunStore

    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    settings.image_id = os.environ["P2C_TEST_IMAGE"]
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses))
        output = asyncio.run(run_workflow(coder, paper))
        assert (output / "a.py").exists()
        report = json.loads((store.root / "report.json").read_text())
        assert report["tests_verified"]
        assert report["outcome"] == "complete"
        assert report["coverage"]["line_percent"] == 100
        assert "100.00% / n/a" in (store.root / "report.md").read_text()


def test_generated_module_import_error_is_repairable(tmp_path):
    work, suite = staged(tmp_path, source="raise ValueError('bad module initialization')\n")
    result = asyncio.run(
        run_check(
            CheckSpec(id="imports", kind="imports", targets=["a"]),
            work,
            suite,
            os.environ["P2C_TEST_IMAGE"],
        )
    )
    assert result.status == "failed"
    assert "bad module initialization" in Path(result.stderr_artifact).read_text()


@pytest.mark.parametrize("include_negative, expected", [(False, 50.0), (True, 100.0)])
def test_runner_measures_branch_coverage_without_blocking_output(
    tmp_path, include_negative, expected
):
    # Arrange
    source = "def absolute(x):\n    if x < 0:\n        return -x\n    return x\n"
    test = "from a import absolute\ndef test_positive():\n    assert absolute(2) == 2\n"
    if include_negative:
        test += "def test_negative():\n    assert absolute(-2) == 2\n"
    work, suite = staged(tmp_path, source=source, test=test)
    spec = CheckSpec(id="tests", kind="pytest", targets=["tests/acceptance/check/test_a.py"])

    # Act
    result = asyncio.run(run_check(spec, work, suite, os.environ["P2C_TEST_IMAGE"]))

    # Assert
    assert result.status == "passed"
    assert result.coverage["branch_percent"] == expected
    assert result.coverage["files"]["a.py"]["missing_lines"] == ([] if include_negative else [3])


def test_coverage_includes_unimported_modules(tmp_path):
    # Arrange
    work, suite = staged(tmp_path, test="def test_ok(): assert True\n")
    (work / "unused.py").write_text("def unused():\n    return 42\n")
    spec = CheckSpec(id="tests", kind="pytest", targets=["tests/acceptance/check/test_a.py"])

    # Act
    result = asyncio.run(run_check(spec, work, suite, os.environ["P2C_TEST_IMAGE"]))

    # Assert
    assert result.status == "passed"
    assert result.coverage["line_percent"] == 0
    assert result.coverage["files"]["unused.py"]["missing_lines"] == [1, 2]


def test_real_test_failure_drives_repair_and_recheck(tmp_path, monkeypatch):
    import json

    from providers import ScriptedProvider
    from slick import prompts
    from test_simple_workflow import case

    from codes.agent import PaperCoder, run_workflow
    from codes.store import RunStore

    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    settings.image_id = os.environ["P2C_TEST_IMAGE"]
    responses[1] = "def f(x): return 0\n"
    responses.append(json.dumps({"files": [{"path": "a.py", "content": "def f(x): return x*x\n"}]}))
    provider = ScriptedProvider(responses)
    with RunStore.create(tmp_path / "run", settings) as store:
        output = asyncio.run(run_workflow(PaperCoder(store, provider), paper))
        assert (output / "a.py").read_text() == "def f(x): return x*x\n"
        assert store.manifest.outcome == "complete" and store.manifest.fixes == 1
        assert "assert 0 == 9" in provider.contexts[-1]
        results = [json.loads(p.read_text()) for p in (store.root / "checks").rglob("result.json")]
        assert sorted(r["status"] for r in results) == ["failed", "passed", "passed", "passed"]


def test_broken_acceptance_keeps_real_generated_draft(tmp_path, monkeypatch):
    import json

    from providers import ScriptedProvider
    from slick import prompts
    from test_simple_workflow import case

    from codes.agent import PaperCoder, run_workflow
    from codes.store import RunStore

    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    settings.image_id = os.environ["P2C_TEST_IMAGE"]
    responses[2] = "import missing_test_dependency\ndef test_value(): pass\n"
    responses.append(json.dumps({"files": [], "notes": "Test dependency is unavailable"}))
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses))
        output = asyncio.run(run_workflow(coder, paper))
        assert (output / "a.py").read_text() == "def f(x): return x*x\n"
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "draft" and not report["tests_verified"]
