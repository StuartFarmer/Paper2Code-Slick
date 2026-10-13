import json

import pytest
from providers import ScriptedExecutor, ScriptedProvider
from test_simple_workflow import case

from codes import workflow


@pytest.mark.parametrize("model", ["codex", "claude", "cluade"])
def test_unbounded_cli_backends_rejected_before_reading_paper(model, capsys):
    with pytest.raises(SystemExit) as error:
        workflow.main(["missing.tex", "--model", model])
    assert error.value.code == 2
    assert "OpenRouter" in capsys.readouterr().err


def test_cli_preserves_nitro_suffix_and_resume_reuses_evidence(tmp_path, monkeypatch):
    source, _, responses = case(tmp_path)
    paper = tmp_path / "paper.md"
    paper.write_text(source)
    provider = ScriptedProvider(responses)
    options = []

    def make_provider(**kwargs):
        options.append(kwargs)
        return provider

    monkeypatch.setattr(workflow, "OpenRouterAPI", make_provider)
    monkeypatch.setattr(workflow, "executor_image", lambda name: ("sha256:image", "linux/arm64"))
    monkeypatch.setattr(workflow, "run_check", ScriptedExecutor())
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
    assert len(provider.contexts) == 4
    assert json.loads((root / "manifest.json").read_text())["outcome"] == "complete"


def test_resume_rejects_model_override_before_reading_run():
    with pytest.raises(SystemExit) as error:
        workflow.main(["--resume", "missing", "--model", "openai/gpt-oss-120b:nitro"])
    assert error.value.code == 2


@pytest.mark.parametrize("explicit_outputs", [False, True])
def test_tex_path_runs_with_nested_export_and_frozen_includes(
    tmp_path, monkeypatch, explicit_outputs
):
    # Arrange
    source, _, responses = case(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.tex").write_text(r"\input{method}")
    (tmp_path / "method.tex").write_text(source)
    provider = ScriptedProvider(responses)
    monkeypatch.setattr(workflow, "OpenRouterAPI", lambda **kwargs: provider)
    monkeypatch.setattr(workflow, "executor_image", lambda name: ("sha256:image", "linux/arm64"))
    monkeypatch.setattr(workflow, "run_check", ScriptedExecutor())
    monkeypatch.setattr(workflow, "cleanup_run", lambda run_id: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-real-key")
    root = tmp_path / "outputs/paper"
    args = ["paper.tex"]
    if explicit_outputs:
        args += ["--output-dir", str(root), "--output-repo-dir", str(root / "repo")]
    # Act
    result = workflow.main(args)
    (tmp_path / "method.tex").unlink()
    resumed = workflow.main(["--resume", str(root)])
    # Assert
    assert result == resumed == 0
    assert (root / "repo/experiment.ipynb").exists()
    assert source in (root / "source/paper.txt").read_text()
    assert source in provider.contexts[0]
    assert len(provider.contexts) == 4


@pytest.mark.parametrize(
    "source_dir", [".", "sources/arXiv-1302.6927v1", "sources/arXiv-1302.6927v1/paper"]
)
def test_automatic_output_names_preserve_prior_runs(tmp_path, monkeypatch, source_dir):
    # Arrange
    monkeypatch.chdir(tmp_path)
    paper = tmp_path / source_dir / "paper.tex"
    paper.parent.mkdir(parents=True, exist_ok=True)
    paper.write_text("A paper")
    name = "paper" if source_dir == "." else "arXiv-1302.6927v1"
    prior = tmp_path / "outputs" / name
    prior.mkdir(parents=True)
    (prior / "keep.txt").write_text("user data")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(workflow, "executor_image", lambda name: ("sha256:image", "linux/arm64"))
    monkeypatch.setattr(workflow, "run", lambda store, paper: 0)
    # Act
    result = workflow.main([str(paper)])
    # Assert
    assert result == 0
    assert (prior / "keep.txt").read_text() == "user data"
    manifest = json.loads((tmp_path / "outputs" / f"{name}-2/manifest.json").read_text())
    assert manifest["output_repo"] == str(tmp_path / "outputs" / f"{name}-2/repo")


@pytest.mark.parametrize("destination", ["run", "run/source", "run/calls/repo", "."])
def test_export_cannot_overlap_controller_state(tmp_path, monkeypatch, destination, capsys):
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.tex").write_text("A paper")
    # Act
    result = workflow.main(["paper.tex", "--output-dir", "run", "--output-repo-dir", destination])
    # Assert
    assert result == 1 and not (tmp_path / "run").exists()
    assert "overlap" in capsys.readouterr().err
