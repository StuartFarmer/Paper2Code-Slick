import json

import pytest
from providers import ScriptedExecutor, ScriptedProvider
from test_verified_workflow import case

from codes import workflow


@pytest.mark.parametrize("model", ["codex", "claude", "cluade"])
def test_unbounded_cli_backends_rejected_before_reading_paper(model, capsys):
    with pytest.raises(SystemExit) as error:
        workflow.main(["missing.tex", "--model", model])
    assert error.value.code == 2
    assert "OpenRouter" in capsys.readouterr().err


def test_cli_preserves_nitro_suffix_and_resume_reuses_evidence(tmp_path, monkeypatch):
    paper, _, responses = case(tmp_path)
    provider = ScriptedProvider(responses)
    options = []

    def make_provider(**kwargs):
        options.append(kwargs)
        return provider

    monkeypatch.setattr(workflow, "OpenRouterAPI", make_provider)
    monkeypatch.setattr(workflow, "executor_image", lambda name: ("sha256:image", "linux/arm64"))
    monkeypatch.setattr(workflow, "run_check", ScriptedExecutor(["failed", "failed"]))
    monkeypatch.setattr(workflow, "cleanup_run", lambda run_id: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-real-key")
    root = tmp_path / "run"
    assert (
        workflow.main(
            [
                str(paper),
                "--model",
                "openai/gpt-oss-120b:nitro",
                "--output-dir",
                str(root),
                "--output-repo-dir",
                str(tmp_path / "repo"),
            ]
        )
        == 0
    )
    assert all(o["model"] == "openai/gpt-oss-120b:nitro" and o["max_retries"] == 0 for o in options)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert workflow.main(["--resume", str(root)]) == 0
    assert len(provider.contexts) == 11
    assert json.loads((root / "manifest.json").read_text())["outcome"] == "complete"


def test_resume_rejects_model_override_before_reading_run():
    with pytest.raises(SystemExit) as error:
        workflow.main(["--resume", "missing", "--model", "openai/gpt-oss-120b:nitro"])
    assert error.value.code == 2
