import asyncio
import json
from pathlib import Path

import pytest
from providers import ScriptedExecutor, ScriptedProvider
from slick import prompts
from test_contracts import spec_plan, suite_for
from test_store import manifest

from codes.agent import PaperCoder
from codes.paper import index_paper
from codes.store import RunStore

PASS = json.dumps({"verdict": "pass", "findings": [], "unresolved_requirement_ids": []})


def candidate(code="def f(x): return x*x\n", path="a.py"):
    return json.dumps(
        {"kind": "candidate", "files": [{"path": path, "content": code}], "notes": ""}
    )


def configured(tmp_path, monkeypatch, responses, statuses=()):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper = tmp_path / "paper.md"
    paper.write_text("Square a number.")
    spec, plan = spec_plan()
    suite = suite_for(plan)
    plan.tasks = plan.tasks[:1]
    suite.files = suite.files[:1]
    suite.properties = suite.properties[:1]
    suite.task_targets = {"a": suite.task_targets["a"]}
    suite.integration_targets = suite.task_targets["a"]
    settings = manifest()
    settings.limits.max_calls = 30
    store = RunStore.create(tmp_path / "run", settings)
    provider = ScriptedProvider(responses)
    runner = ScriptedExecutor(statuses)
    coder = PaperCoder(store, provider, executor=runner)
    coder.configure_run(index_paper(paper), spec, plan, suite)
    return store, coder, provider, runner


def test_one_task_requires_current_checks_and_review(tmp_path, monkeypatch):
    store, coder, provider, runner = configured(tmp_path, monkeypatch, [candidate(), PASS])
    with store:
        result = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert result.state == "accepted"
        assert [c.kind for c in runner.calls] == ["syntax", "imports", "pytest"]
        assert len(provider.contexts) == 2
        assert asyncio.run(coder.execute_task(coder.plan.tasks[0])).state == "accepted"
        assert len(provider.contexts) == 2


def test_false_passing_review_cannot_override_failed_check(tmp_path, monkeypatch):
    diagnosis = json.dumps(
        {
            "category": "implementation",
            "hypothesis": "wrong formula",
            "evidence_artifacts": ["check"],
            "affected_paths": ["a.py"],
            "proposed_fix": "square",
            "regression_check": "f(2)=4",
        }
    )
    store, coder, provider, runner = configured(
        tmp_path,
        monkeypatch,
        [candidate("def f(x): return 0\n"), PASS, diagnosis, candidate(), PASS],
        ["passed", "passed", "failed", "passed", "passed", "passed"],
    )
    with store:
        result = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert result.state == "accepted" and result.fixes == 1
        assert len(provider.contexts) == 5
        assert len(runner.calls) == 6


def test_foreign_file_and_repeated_context_requests_block(tmp_path, monkeypatch):
    request = json.dumps(
        {
            "kind": "needs_context",
            "source_ids": ["s-0001"],
            "interface_ids": [],
            "paths": [],
            "reason": "more",
        }
    )
    store, coder, _, _ = configured(tmp_path, monkeypatch, [request] * 3)
    with store:
        result = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert result.state == "blocked" and result.context_requests == 2


def test_stale_execution_evidence_cannot_accept_task(tmp_path, monkeypatch):
    store, coder, _, runner = configured(tmp_path, monkeypatch, [candidate(), PASS])

    async def stale(*args, **kwargs):
        result = await runner(*args, **kwargs)
        result.candidate_hash = "wrong"
        return result

    coder.executor = stale
    with store:
        result = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert result.state == "draft"
        assert not coder.accepted(coder.plan.tasks[0])
        assert "match" in result.blocker


def test_foreign_owned_path_blocks_before_execution(tmp_path, monkeypatch):
    store, coder, _, runner = configured(tmp_path, monkeypatch, [candidate(path="foreign.py")])
    with store:
        result = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert result.state == "blocked"
        assert runner.calls == []


def test_exhausted_repairs_keep_a_draft_without_claiming_acceptance(tmp_path, monkeypatch):
    diagnosis = json.dumps(
        {
            "category": "implementation",
            "hypothesis": "wrong output",
            "evidence_artifacts": ["check"],
            "affected_paths": ["a.py"],
            "proposed_fix": "fix the formula",
            "regression_check": "pytest",
        }
    )
    responses = [
        candidate("def f(x): return 0\n"),
        PASS,
        diagnosis,
        candidate("def f(x): return 1\n"),
        PASS,
        diagnosis,
        candidate("def f(x): return 2\n"),
        PASS,
    ]
    store, coder, provider, _ = configured(
        tmp_path, monkeypatch, responses + [PASS], ["passed", "passed", "failed"] * 4
    )
    store.manifest.output_repo = str(tmp_path / "export")
    with store:
        record = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert record.state == "draft" and record.fixes == 2
        assert not record.diagnosis_artifact
        record.state = "pending"
        asyncio.run(coder.execute_plan())
        assert len(provider.contexts) == 9
        assert record.fixes == 2 and record.state == "draft"
        output = asyncio.run(coder.finish())
        assert (output / "a.py").read_text() == "def f(x): return 2\n"
        report = json.loads((store.root / "report.json").read_text())
        assert report["generation_complete"] and not report["tests_verified"]


@pytest.mark.parametrize("state", ["cancelled", "checking", "reviewing"])
def test_interrupted_verification_resumes_drafting(tmp_path, monkeypatch, state):
    store, coder, provider, _ = configured(tmp_path, monkeypatch, [candidate()])
    with store:
        coder.suite = None
        asyncio.run(coder.execute_plan())
        record = coder.records["a"]
        record.state = state
        store.save_task(record)
        asyncio.run(asyncio.wait_for(coder.execute_plan(), timeout=1))
        assert record.state == "draft"
        assert len(provider.contexts) == 1


@pytest.mark.parametrize("category", ["test", "spec"])
def test_nonimplementation_diagnosis_is_not_a_pending_repair(tmp_path, monkeypatch, category):
    diagnosis = json.dumps(
        {
            "category": category,
            "hypothesis": "Incorrect expectation",
            "evidence_artifacts": ["check"],
            "affected_paths": ["a.py"],
            "proposed_fix": "Review expectation",
            "regression_check": "pytest",
        }
    )
    store, coder, _, _ = configured(
        tmp_path, monkeypatch, [candidate(), PASS, diagnosis], ["passed", "passed", "failed"]
    )
    with store:
        record = asyncio.run(coder.execute_task(coder.plan.tasks[0]))
        assert record.state == "draft" and record.fixes == 0
        assert not record.diagnosis_artifact


def test_interrupted_reserved_repair_is_consumed_once(tmp_path, monkeypatch):
    store, coder, provider, _ = configured(tmp_path, monkeypatch, [candidate(), candidate(), PASS])
    with store:
        suite = coder.suite
        coder.suite = None
        asyncio.run(coder.execute_plan())
        record = coder.records["a"]
        record.fixes = store.manifest.limits.code_fixes
        record.diagnosis_artifact = store.save_artifact(
            "pending-diagnosis.json", json.dumps({"hypothesis": "Fix formula"})
        )
        record.state = "cancelled"
        asyncio.run(coder.execute_plan())
        coder.suite = suite
        record.state = "pending"
        asyncio.run(coder.execute_plan())
        assert record.state == "accepted" and not record.diagnosis_artifact
        assert record.fixes == 2 and len(provider.contexts) == 3
