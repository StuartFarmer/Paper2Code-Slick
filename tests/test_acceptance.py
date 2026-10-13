import asyncio
import json
from pathlib import Path

from providers import ScriptedExecutor, ScriptedProvider
from slick import prompts
from test_contracts import spec_plan, suite_for
from test_store import manifest

from codes.agent import PaperCoder
from codes.paper import index_paper
from codes.store import RunStore


def test_planning_fragments_are_validated_and_reused_on_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    source = tmp_path / "paper.md"
    source.write_text("A mathematical method.")
    index = index_paper(source)
    spec, plan = spec_plan()
    provider = ScriptedProvider(
        [
            '{"requirements":'
            + spec.model_dump_json().split('"requirements":', 1)[1].split(',"interfaces":', 1)[0]
            + ',"unresolved_references":[]}',
            spec.model_dump_json(),
            '{"verdict":"pass","findings":[],"unresolved_requirement_ids":[]}',
            plan.model_dump_json(),
        ]
    )
    settings = manifest()
    settings.limits.max_calls = 20
    with RunStore.create(tmp_path / "run", settings) as store:
        coder = PaperCoder(store, provider)
        actual_spec, actual_plan = asyncio.run(coder.prepare_plan(index))
        assert actual_spec == spec and actual_plan == plan
        assert len(provider.contexts) == 4
        assert asyncio.run(coder.prepare_plan(index)) == (spec, plan)
        assert len(provider.contexts) == 4


def test_suite_preparation_cannot_see_candidate_code(tmp_path, monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    source = tmp_path / "paper.md"
    source.write_text("Method.")
    spec, plan = spec_plan()
    plan.tasks = plan.tasks[:1]
    suite = suite_for(spec_plan()[1])
    task_suite = suite.model_copy(
        update={
            "files": suite.files[:1],
            "properties": suite.properties[:1],
            "task_targets": {"a": suite.task_targets["a"]},
            "integration_targets": [],
        }
    )
    integration = task_suite.model_copy(deep=True)
    integration.files[0].path = "tests/acceptance/integration/test_method.py"
    integration.properties[0].id = "p-integration"
    integration.properties[0].node_ids = [integration.files[0].path + "::test_value"]
    integration.task_targets = {}
    integration.integration_targets = integration.properties[0].node_ids
    pass_review = json.dumps({"verdict": "pass", "findings": [], "unresolved_requirement_ids": []})
    provider = ScriptedProvider(
        [task_suite.model_dump_json(), pass_review, integration.model_dump_json(), pass_review]
    )
    settings = manifest()
    settings.limits.max_calls = 10
    with RunStore.create(tmp_path / "run", settings) as store:
        runner = ScriptedExecutor(["failed", "failed"])
        coder = PaperCoder(store, provider, executor=runner)
        result = asyncio.run(coder.prepare_acceptance(spec, plan, index_paper(source)))
        assert len(result.files) == 2
        assert len(provider.contexts) == 4
        assert "candidate_files" not in provider.contexts[0]
        assert "suite.json" in store.artifacts
        assert len(runner.calls) == 2
        assert "NotImplementedError" in provider.contexts[1]


def test_contract_scaffolds_raise_without_host_execution():
    from codes.execution import contract_scaffolds

    spec, plan = spec_plan()
    files = contract_scaffolds(spec, plan)
    assert set(files) == {"a.py", "b.py", "c.py", "d.py"}
    assert "def f(" in files["a.py"] and "raise NotImplementedError" in files["a.py"]


def test_vacuous_suite_cannot_freeze_even_if_reviewer_would_pass(tmp_path, monkeypatch):
    import pytest
    from test_verified_workflow import case

    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    paper, settings, responses = case(tmp_path)
    spec, plan = spec_plan()
    plan.tasks = plan.tasks[:1]
    with RunStore.create(tmp_path / "run", settings) as store:
        provider = ScriptedProvider(responses[4:8])
        coder = PaperCoder(store, provider, executor=ScriptedExecutor(["passed", "passed"]))
        with pytest.raises(ValueError, match="scaffold"):
            asyncio.run(coder.prepare_acceptance(spec, plan, index_paper(paper)))
        assert "suite.json" not in store.artifacts
