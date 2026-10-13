import asyncio
import json
from pathlib import Path

from providers import ScriptedExecutor, ScriptedProvider
from slick import prompts
from test_contracts import spec_plan, suite_for
from test_store import manifest
from test_task_loop import PASS, candidate

from codes.agent import PaperCoder, run_verified
from codes.paper import index_paper
from codes.store import RunStore


def case(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_text("Compute the square of a real scalar.")
    spec, plan = spec_plan()
    suite = suite_for(plan)
    plan.tasks = plan.tasks[:1]
    suite.files = suite.files[:1]
    suite.properties = suite.properties[:1]
    suite.files[0].content = "from a import f\ndef test_value():\n    assert f(2) == 4\n"
    suite.task_targets = {"a": suite.task_targets["a"]}
    suite.integration_targets = []
    integration = suite.model_copy(deep=True)
    integration.files[0].path = "tests/acceptance/integration/test_method.py"
    integration.properties[0].id = "integration"
    integration.properties[0].node_ids = [integration.files[0].path + "::test_value"]
    integration.task_targets = {}
    integration.integration_targets = integration.properties[0].node_ids
    responses = [
        json.dumps(
            {
                "requirements": [r.model_dump() for r in spec.requirements],
                "unresolved_references": [],
            }
        ),
        spec.model_dump_json(),
        PASS,
        plan.model_dump_json(),
        candidate(),
        suite.model_dump_json(),
        PASS,
        integration.model_dump_json(),
        PASS,
        PASS,
        PASS,
    ]
    settings = manifest()
    settings.limits.max_calls = 30
    settings.output_repo = str(tmp_path / "export")
    return paper, settings, responses


def test_complete_verified_flow_and_no_call_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    provider = ScriptedProvider(responses)
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, provider, executor=ScriptedExecutor(["failed", "failed"]))
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        assert (output / "a.py").read_text() == "def f(x): return x*x\n"
        report = json.loads((store.root / "report.json").read_text())
        assert report["integration_verified"] is True
        assert report["measured_cost"] is None
        assert len(provider.contexts) == 11
    with RunStore.open(tmp_path / "run") as store:
        resumed = ScriptedProvider([])
        coder = PaperCoder(store, resumed, executor=ScriptedExecutor())
        assert asyncio.run(run_verified(coder, index_paper(paper))) == output
        assert resumed.contexts == []


def test_exhausted_budget_retains_unverified_export(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    settings.limits.max_calls = 9
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(
            store, ScriptedProvider(responses), executor=ScriptedExecutor(["failed", "failed"])
        )
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        assert (output / "a.py").exists()
        assert json.loads((store.root / "report.json").read_text())["outcome"] == "incomplete"


def test_integration_regression_reopens_task_with_bounded_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    diagnosis = json.dumps(
        {
            "category": "implementation",
            "hypothesis": "integration defect",
            "evidence_artifacts": ["integration"],
            "affected_paths": ["a.py"],
            "proposed_fix": "correct expression",
            "regression_check": "integration",
        }
    )
    responses = responses[:10] + [diagnosis, candidate("def f(x): return x ** 2\n"), PASS, PASS]
    scripted = ScriptedExecutor(["failed", "failed", "passed", "passed", "passed", "failed"])

    async def executor(*args, **kwargs):
        result = await scripted(*args, **kwargs)
        if result.check_id == "integration" and result.status == "failed":
            result.failed_nodes = ["tests/acceptance/integration/test_method.py::test_value"]
        return result

    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, ScriptedProvider(responses), executor=executor)
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        assert output is not None
        assert coder.records["a"].fixes == 1


def test_extracted_missing_method_reference_is_reported_on_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    extraction = json.loads(responses[0])
    warning = "The core recurrence equation is missing; implementation cannot be determined."
    extraction["unresolved_references"] = [warning]
    responses[0] = json.dumps(extraction)
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(
            store, ScriptedProvider(responses), executor=ScriptedExecutor(["failed", "failed"])
        )
        output = asyncio.run(run_verified(coder, index_paper(paper)))
        report = json.loads((store.root / "report.json").read_text())
        assert warning in report["unresolved_references"]
        assert report["outcome"] != "complete"
        assert (output / "a.py").exists()
