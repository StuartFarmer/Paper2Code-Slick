import asyncio
import json
from pathlib import Path

import pytest
from providers import ScriptedExecutor, ScriptedProvider
from slick import prompts
from test_verified_workflow import case

from codes.agent import PaperCoder, run_verified
from codes.paper import index_paper
from codes.store import RunStore


@pytest.fixture(autouse=True)
def templates(monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )


def draft_case(tmp_path):
    paper, settings, responses = case(tmp_path)
    return paper, settings, responses


def test_spec_objection_is_reported_but_code_is_generated(tmp_path):
    paper, settings, responses = draft_case(tmp_path)
    responses[2] = json.dumps(
        {"verdict": "blocked", "findings": [], "unresolved_requirement_ids": ["r"]}
    )
    with RunStore.create(tmp_path / "run", settings) as store:
        provider = ScriptedProvider(responses)
        coder = PaperCoder(store, provider, executor=ScriptedExecutor(["failed", "failed"]))
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        assert (output / "a.py").read_text() == "def f(x): return x*x\n"
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "draft" and report["generation_complete"]
        assert any("Specification review" in w for w in report["warnings"])
        assert "candidate_files" not in provider.contexts[5]


def test_bad_test_suite_does_not_destroy_a_generated_draft(tmp_path):
    paper, settings, responses = draft_case(tmp_path)
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(
            store,
            ScriptedProvider(responses[:6]),
            executor=ScriptedExecutor(["infrastructure_error"]),
        )
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        assert (output / "a.py").exists()
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "draft" and not report["tests_verified"]


def test_budget_exhaustion_exports_unverified_code(tmp_path):
    paper, settings, responses = draft_case(tmp_path)
    settings.limits.max_calls = 5
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses))
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        assert (output / "a.py").exists()
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "incomplete" and not report["tests_verified"]
        assert report["calls_reserved"] == 5


def test_dependency_drafts_allow_downstream_generation(tmp_path):
    from test_contracts import spec_plan
    from test_store import manifest
    from test_task_loop import candidate

    source = tmp_path / "paper.md"
    source.write_text("A small method")
    spec, plan = spec_plan()
    plan.tasks = plan.tasks[:2]
    settings = manifest()
    settings.output_repo = str(tmp_path / "repo")
    with RunStore.create(tmp_path / "run", settings) as store:
        provider = ScriptedProvider(
            [candidate(), candidate("from a import f\ndef g(x): return f(x)\n", "b.py")]
        )
        coder = PaperCoder(store, provider)
        coder.configure_run(index_paper(source), spec, plan, None)
        asyncio.run(coder.execute_plan())
        assert all(r.state == "draft" for r in coder.records.values())
        assert "def f(x): return x*x" in provider.contexts[1]
        output = asyncio.run(coder.finish())
        assert (output / "a.py").exists() and (output / "b.py").exists()
        report = json.loads((store.root / "report.json").read_text())
        assert report["generation_complete"] and not report["tests_verified"]


def test_draft_export_never_overwrites_user_edits(tmp_path):
    paper, settings, responses = draft_case(tmp_path)
    settings.limits.max_calls = 5
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses))
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        (output / "a.py").write_text("user code")
        revised = coder.export_draft()
        assert revised != output
        assert (revised / "a.py").read_text() == "def f(x): return x*x\n"
        assert (output / "a.py").read_text() == "user code"


def test_export_failure_still_writes_report(tmp_path, monkeypatch):
    paper, settings, responses = draft_case(tmp_path)
    settings.limits.max_calls = 5
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses))

        def unavailable():
            raise OSError("Export unavailable")

        monkeypatch.setattr(coder, "export_draft", unavailable)
        assert asyncio.run(run_verified(coder, index_paper(paper))) is None
        report = json.loads((store.root / "report.json").read_text())
        assert report["outcome"] == "incomplete"
        assert any("Export unavailable" in w for w in report["warnings"])


def test_matching_export_recovers_manifest_metadata(tmp_path):
    paper, settings, responses = draft_case(tmp_path)
    settings.limits.max_calls = 5
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses))
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        store.manifest.export_path = store.manifest.export_hash = ""
        assert coder.export_draft() == output
        assert store.manifest.export_path == str(output)
        assert store.manifest.export_hash
