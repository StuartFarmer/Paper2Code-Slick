import asyncio
from pathlib import Path

import pytest
from providers import ScriptedProvider
from slick import prompts
from test_contracts import spec_plan, suite_for
from test_store import manifest

from codes.agent import OPERATIONS, PaperCoder
from codes.context import bounded_groups, build_packet, check_input_size, resolve_context
from codes.contracts import ContextRequest
from codes.paper import index_paper
from codes.store import RunStore


@pytest.fixture(autouse=True)
def prompt_root(monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )


def test_all_operations_render_schemas():
    async def check():
        owner = object.__new__(PaperCoder)
        for name in OPERATIONS:
            method = getattr(PaperCoder, name)
            text = await method.render(owner, {"sentinel": "bounded-input"})
            assert "bounded-input" in text and "JSON" in text
            assert "properties" in text or "oneOf" in text or "anyOf" in text

    asyncio.run(check())


def test_exact_rendered_input_limit():
    check_input_size("x" * 32768)
    with pytest.raises(ValueError):
        check_input_size("x" * 32769)
    with pytest.raises(ValueError):
        check_input_size("λ" * 16385)


def test_bounded_groups_preserve_all_records():
    records = [{"id": f"r-{i}", "evidence": "λ" * 300} for i in range(100)]
    groups = list(bounded_groups(records, 4096))
    assert len(groups) > 1
    assert [record for group in groups for record in group] == records
    with pytest.raises(ValueError):
        list(bounded_groups([{"large": "λ" * 3000}], 4096))


def test_packet_contains_only_related_evidence_and_rejects_unrelated_paths(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_text("Method evidence.")
    index = index_paper(paper)
    spec, plan = spec_plan()
    suite = suite_for(plan)
    packet = build_packet(plan.tasks[1], spec, index, {"a.py": "def f(x): return x*x"}, suite)
    assert "a.py" in packet["dependency_files"]
    assert all("/b/" in f["path"] for f in packet["acceptance_files"])
    request = ContextRequest(
        kind="needs_context", source_ids=[], interface_ids=[], paths=["secret.py"], reason="want it"
    )
    with pytest.raises(ValueError):
        resolve_context(request, packet, index, spec)


def test_schema_healing_uses_fresh_bounded_calls_and_keeps_raw_evidence(tmp_path):
    with RunStore.create(
        tmp_path / "run",
        manifest().model_copy(
            update={"limits": manifest().limits.model_copy(update={"max_calls": 4})}
        ),
    ) as store:
        provider = ScriptedProvider(
            ['{"requirements":', '{"requirements": [], "unresolved_references": []}']
        )
        coder = PaperCoder(store, provider)
        result = asyncio.run(coder.invoke("extract_requirements", {"excerpt": "fact"}))
        assert result.requirements == []
        assert len(provider.contexts) == store.manifest.calls_reserved == 2
        assert "requirements" in store.read_artifact("calls/call-00001/history.json")
        assert "validation" in provider.contexts[1].lower()
        assert "Extract implementable requirements from this excerpt." not in provider.contexts[1]


def test_provider_value_error_is_not_schema_healed(tmp_path):
    with RunStore.create(tmp_path / "run", manifest()) as store:
        provider = ScriptedProvider([ValueError("provider config invalid")])
        with pytest.raises(ValueError, match="provider config"):
            asyncio.run(PaperCoder(store, provider).invoke("extract_requirements", {}))
        assert len(provider.contexts) == 1


def test_dependency_context_can_expand_without_initial_ancestor_dump(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_text("method")
    spec, plan = spec_plan()
    index = index_paper(paper)
    dependencies = {"a.py": "def f(x): return x*x", "helper.py": "x=1"}
    packet = build_packet(plan.tasks[1], spec, index, dependencies, suite_for(plan))
    assert "helper.py" not in packet["dependency_files"]
    request = ContextRequest(
        kind="needs_context",
        source_ids=[],
        interface_ids=[],
        paths=["helper.py"],
        reason="check helper",
    )
    expanded = resolve_context(request, packet, index, spec, dependencies)
    assert expanded["dependency_files"]["helper.py"] == "x=1"
