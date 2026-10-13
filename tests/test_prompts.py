import asyncio
import json
from pathlib import Path

import pytest
from providers import ScriptedProvider
from slick import prompts
from test_simple_workflow import case

from codes.agent import OPERATIONS, PaperCoder
from codes.store import RunStore


@pytest.fixture(autouse=True)
def templates(monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )


def test_all_operations_render_from_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def check():
        owner = object.__new__(PaperCoder)
        for name in [*OPERATIONS, "repair_json"]:
            text = await getattr(PaperCoder, name).render(owner, {"sentinel": "input"})
            assert "sentinel" in text

    asyncio.run(check())


def test_bad_json_is_repaired_with_feedback_and_raw_logs(tmp_path):
    paper, settings, responses = case(tmp_path)
    provider = ScriptedProvider(['{"files":', responses[0]])
    with RunStore.create(tmp_path / "run", settings) as store:
        plan = asyncio.run(PaperCoder(store, provider).invoke("plan", {"paper": paper}))
        assert plan.files[0].path == "a.py"
        assert len(provider.contexts) == 2
        assert "validation_errors" in provider.contexts[1]
        assert "files" in store.read_artifact("calls/call-00001/history.json")


def test_unsafe_plan_path_is_corrected_before_generation(tmp_path):
    paper, settings, responses = case(tmp_path)
    invalid = json.loads(responses[0])
    invalid["files"][0]["path"] = "../escape.py"
    provider = ScriptedProvider([json.dumps(invalid), responses[0]])
    with RunStore.create(tmp_path / "run", settings) as store:
        result = asyncio.run(PaperCoder(store, provider).invoke("plan", {"paper": paper}))
        assert result.files[0].path == "a.py"
        assert "Unsafe generated filename" in provider.contexts[1]


def test_provider_error_is_not_misreported_as_json_error(tmp_path):
    _, settings, _ = case(tmp_path)
    provider = ScriptedProvider([ValueError("provider configuration")])
    with RunStore.create(tmp_path / "run", settings) as store:
        with pytest.raises(ValueError, match="provider configuration"):
            asyncio.run(PaperCoder(store, provider).invoke("plan", {}))
        assert len(provider.contexts) == 1
