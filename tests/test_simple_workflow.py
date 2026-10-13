import asyncio
import json
from pathlib import Path

import pytest
from providers import ScriptedExecutor, ScriptedProvider
from slick import prompts

from codes.agent import PaperCoder, run_workflow
from codes.contracts import Limits, RunManifest
from codes.store import RunStore


def case(tmp_path):
    paper = "Implement a.py with f(x) returning x squared."
    manifest = RunManifest(
        run_id="simple-test",
        input_hashes={},
        image_id="sha256:test",
        platform="linux/arm64",
        models={"worker": "test", "planner": "test"},
        output_repo=str(tmp_path / "repo"),
        limits=Limits(max_calls=30),
    )
    replies = [
        json.dumps(
            {
                "overview": "a.f(x) returns x squared.",
                "files": [{"path": "a.py", "instructions": "Implement f(x). Return x*x."}],
            }
        ),
        "def f(x): return x*x\n",
        "from a import f\ndef test_square(): assert f(3) == 9\n",
    ]
    return paper, manifest, replies


@pytest.fixture(autouse=True)
def templates(monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )


def test_three_calls_produce_and_check_a_repository(tmp_path):
    paper, settings, responses = case(tmp_path)
    provider = ScriptedProvider(responses)
    executor = ScriptedExecutor()
    with RunStore.create(tmp_path / "run", settings) as store:
        output = asyncio.run(run_workflow(PaperCoder(store, provider, executor=executor), paper))
        assert (output / "a.py").read_text() == responses[1]
        assert (output / "tests/acceptance/test_generated.py").exists()
        assert len(provider.contexts) == 3
        assert [c.kind for c in executor.calls] == ["syntax", "pytest"]
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "complete" and report["tests_verified"]
        assert responses[1].strip() in provider.contexts[2].replace("\\n", "\n")


def test_failure_output_goes_directly_to_bounded_code_repair(tmp_path):
    paper, settings, responses = case(tmp_path)
    responses[1] = "def f(x): return 0\n"
    responses.append(
        json.dumps(
            {
                "files": [{"path": "a.py", "content": "def f(x): return x*x\n"}],
                "notes": "Fixed constant output.",
            }
        )
    )
    provider = ScriptedProvider(responses)
    with RunStore.create(tmp_path / "run", settings) as store:
        output = asyncio.run(
            run_workflow(
                PaperCoder(store, provider, executor=ScriptedExecutor(["passed", "failed"])), paper
            )
        )
        assert (output / "a.py").read_text() == "def f(x): return x*x\n"
        assert "scripted" in provider.contexts[-1] or "NotImplementedError" in provider.contexts[-1]
        assert store.manifest.fixes == 1 and len(provider.contexts) == 4


def test_test_author_failure_keeps_code_and_reports_draft(tmp_path):
    paper, settings, responses = case(tmp_path)
    responses[2] = RuntimeError("provider offline")
    with RunStore.create(tmp_path / "run", settings) as store:
        output = asyncio.run(run_workflow(PaperCoder(store, ScriptedProvider(responses)), paper))
        assert (output / "a.py").exists()
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "draft" and not report["tests_verified"]
        assert "provider offline" in report["error"]


def test_budget_after_generation_keeps_code(tmp_path):
    paper, settings, responses = case(tmp_path)
    settings.limits.max_calls = 2
    with RunStore.create(tmp_path / "run", settings) as store:
        output = asyncio.run(run_workflow(PaperCoder(store, ScriptedProvider(responses)), paper))
        assert (output / "a.py").exists() and store.manifest.calls_reserved == 2


def test_plan_has_no_dependency_or_interface_registry(tmp_path):
    paper, settings, responses = case(tmp_path)
    plan = json.loads(responses[0])
    plan["files"][0]["depends_on"] = ["I-mean"]
    responses[0] = json.dumps(plan)
    with RunStore.create(tmp_path / "run", settings) as store:
        output = asyncio.run(
            run_workflow(
                PaperCoder(store, ScriptedProvider(responses), executor=ScriptedExecutor()), paper
            )
        )
        assert (output / "a.py").exists()


def test_parallel_file_failure_preserves_successful_sibling(tmp_path):
    paper, settings, responses = case(tmp_path)
    plan = json.loads(responses[0])
    plan["files"].append({"path": "b.py", "instructions": "Implement g(x)."})
    responses = [json.dumps(plan), responses[1], RuntimeError("worker unavailable"), responses[2]]
    with RunStore.create(tmp_path / "run", settings) as store:
        provider = ScriptedProvider(responses)
        output = asyncio.run(
            run_workflow(PaperCoder(store, provider, executor=ScriptedExecutor()), paper)
        )
        assert (output / "a.py").exists() and not (output / "b.py").exists()
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "draft" and not report["generation_complete"]
        assert "worker unavailable" in report["warnings"][0]


def test_resume_does_not_regenerate_files_or_exceed_repair_limit(tmp_path):
    paper, settings, responses = case(tmp_path)
    revision = json.dumps({"files": [{"path": "a.py", "content": "def f(x): return 0\n"}]})
    responses.extend([revision, revision])
    executor = ScriptedExecutor(["passed", "failed"] * 4)
    root = tmp_path / "run"
    with RunStore.create(root, settings) as store:
        output = asyncio.run(
            run_workflow(PaperCoder(store, ScriptedProvider(responses), executor=executor), paper)
        )
        assert store.manifest.fixes == 2 and store.manifest.calls_reserved == 5
        assert (output / "a.py").exists()
    with RunStore.open(root) as store:
        provider = ScriptedProvider([])
        output = asyncio.run(run_workflow(PaperCoder(store, provider, executor=executor), paper))
        assert not provider.contexts and store.manifest.fixes == 2
        assert store.manifest.outcome == "draft" and (output / "a.py").exists()


def test_resume_preserves_user_edits(tmp_path):
    paper, settings, responses = case(tmp_path)
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses), executor=ScriptedExecutor())
        output = asyncio.run(run_workflow(coder, paper))
        (output / "a.py").write_text("user changes")
        revised = coder.finish()
        assert revised != output
        assert (output / "a.py").read_text() == "user changes"
        assert (revised / "a.py").read_text() == responses[1]


def test_repair_cannot_overwrite_tests_or_escape_repo(tmp_path):
    _, settings, _ = case(tmp_path)
    from codes.contracts import Revision

    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider([]))
        for path in ["../outside.py", "tests/acceptance/test_generated.py"]:
            with pytest.raises(ValueError):
                coder.validate_output("repair", Revision(files=[{"path": path, "content": "pass"}]))


def test_export_failure_still_reports_saved_generation(tmp_path, monkeypatch):
    paper, settings, responses = case(tmp_path)
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses), executor=ScriptedExecutor())
        asyncio.run(coder.run(paper))

        def fail(*args):
            raise OSError("Export disk unavailable")

        monkeypatch.setattr("codes.agent.materialize_snapshot", fail)
        assert coder.finish() is None
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "failed" and report["generation_complete"]
        assert "Export disk unavailable" in report["error"]
