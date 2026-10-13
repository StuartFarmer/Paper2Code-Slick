import asyncio
import json
from pathlib import Path

import pytest
from slick import prompts

from codes.workflow import PaperCoder, load_paper
from providers import ScriptedProvider


def responses(files=("src/model.py", "main.py")):
    tasks = {
        "Task list": list(files),
        "Logic Analysis": [[f, "Implement " + f] for f in files],
    }
    return [
        "Reproduce the supplied experiment.",
        '[CONTENT]{"File list": ["src/model.py", "main.py"]}[/CONTENT]',
        "[CONTENT]" + json.dumps(tasks) + "[/CONTENT]",
        "```yaml\nseed: 7\n```",
        "Analyze the model.",
        "Analyze the entry point.",
        "```python\nclass Model: pass\n```",
        "```python\nfrom src.model import Model\n```",
    ]


@pytest.fixture(autouse=True)
def template_root(monkeypatch):
    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )


def run(tmp_path, supplied=None):
    provider = ScriptedProvider(responses() if supplied is None else supplied)
    coder = PaperCoder("Paper body", "JSON", provider, tmp_path / "artifacts", tmp_path / "repo")
    return coder, provider


def test_complete_workflow_preserves_order_context_and_session_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    coder, provider = run(tmp_path)
    result = asyncio.run(coder.run())
    assert result == tmp_path / "repo"
    assert (result / "config.yaml").read_text() == "seed: 7\n"
    assert (result / "src/model.py").read_text() == "class Model: pass\n"
    assert (result / "main.py").read_text() == "from src.model import Model\n"
    assert len(provider.contexts) == 8
    assert "Reproduce the supplied experiment." in provider.contexts[1]
    assert "Analyze the model." in provider.contexts[6]
    assert "class Model: pass" in provider.contexts[7]
    assert "class Model: pass" not in provider.contexts[6]
    history = json.loads((tmp_path / "artifacts/calls/planning.json").read_text())
    assert len(history) == 4
    assert history[0]["text"] == "Reproduce the supplied experiment."
    assert "Paper body" in history[0]["context"]
    tasks = json.loads((tmp_path / "artifacts/planning/tasks.json").read_text())
    assert tasks["Task list"] == ["src/model.py", "main.py"]
    assert (tmp_path / "artifacts/planning/config.yaml").read_text() == "seed: 7\n"
    assert (tmp_path / "artifacts/analysis/src/model.py.txt").exists()


@pytest.mark.parametrize(
    "filename",
    [
        "../escaped.py",
        "/tmp/escaped.py",
        ".git/config",
        "src/../../escaped.py",
        "src/../config.yaml",
    ],
)
def test_generated_paths_cannot_escape_or_alias_config(tmp_path, filename):
    coder, provider = run(tmp_path, responses((filename,)))
    with pytest.raises(ValueError):
        asyncio.run(coder.run())
    assert not (tmp_path / "repo/config.yaml").exists()
    assert len(provider.contexts) == 3


def test_generated_paths_cannot_follow_existing_symlinks(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "repo/src").symlink_to(tmp_path / "outside", target_is_directory=True)
    coder, _ = run(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(coder.run())
    assert not list((tmp_path / "outside").iterdir())


@pytest.mark.parametrize(
    "bad_tasks",
    [
        "not JSON",
        '[CONTENT]{"Task list": [], "Logic Analysis": []}[/CONTENT]',
        '[CONTENT]{"Task list": ["main.py", "main.py"], "Logic Analysis": []}[/CONTENT]',
        '[CONTENT]{"Task list": ["main.py",], "Logic Analysis": []}[/CONTENT]',
    ],
)
def test_invalid_plan_stops_and_retains_raw_response(tmp_path, bad_tasks):
    supplied = responses()
    supplied[2] = bad_tasks
    coder, provider = run(tmp_path, supplied)
    with pytest.raises(ValueError):
        asyncio.run(coder.run())
    assert len(provider.contexts) == 3
    history = json.loads((tmp_path / "artifacts/calls/planning.json").read_text())
    assert history[-1]["text"] == bad_tasks
    assert not (tmp_path / "repo/config.yaml").exists()


def test_missing_config_fence_stops_before_writing_repository(tmp_path):
    supplied = responses()
    supplied[3] = "I cannot provide a configuration."
    coder, _ = run(tmp_path, supplied)
    with pytest.raises(ValueError, match="YAML"):
        asyncio.run(coder.run())
    assert not (tmp_path / "repo/config.yaml").exists()


def test_provider_failure_propagates_without_retry_and_keeps_progress(tmp_path):
    coder, provider = run(tmp_path, responses()[:5] + [RuntimeError("offline")])
    with pytest.raises(RuntimeError, match="offline"):
        asyncio.run(coder.run())
    assert len(provider.contexts) == 6
    assert (tmp_path / "artifacts/analysis/src/model.py.txt").exists()
    assert not (tmp_path / "repo/main.py").exists()
    assert "offline" in (tmp_path / "artifacts/failure.json").read_text()


def test_loads_json_with_span_cleanup_and_latex_verbatim(tmp_path):
    paper = tmp_path / "paper.json"
    paper.write_text(
        '{"title": "Paper", "authors": ["A"], "body_text": [{"text": "Method", "cite_spans": []}]}'
    )
    text, format = load_paper(paper)
    assert format == "JSON"
    assert "Method" in text and "cite_spans" not in text and "authors" not in text
    paper = tmp_path / "paper.tex"
    paper.write_text("\\section{Method}\nPaper body")
    assert load_paper(paper) == ("\\section{Method}\nPaper body", "LaTeX")


def test_config_is_not_regenerated_and_plain_code_is_preserved(tmp_path):
    supplied = responses(("config.yaml", "main.py"))[:4]
    supplied += ["Analyze main.", "<think>Reasoning</think>print('hello')\n"]
    coder, provider = run(tmp_path, supplied)
    asyncio.run(coder.run())
    assert len(provider.contexts) == 6
    assert (tmp_path / "repo/config.yaml").read_text() == "seed: 7\n"
    assert (tmp_path / "repo/main.py").read_text() == "print('hello')\n"
    record = json.loads((tmp_path / "artifacts/calls/coding/main.py.json").read_text())
    assert record[0]["text"].startswith("<think>")


def test_empty_generation_stops_without_writing_code(tmp_path):
    coder, _ = run(tmp_path, responses()[:6] + ["  "])
    with pytest.raises(ValueError, match="empty response"):
        asyncio.run(coder.run())
    assert not (tmp_path / "repo/src/model.py").exists()


@pytest.mark.parametrize(
    "model, provider_name",
    [
        (None, "CodexCLI"),
        ("codex", "CodexCLI"),
        ("claude", "ClaudeCLI"),
        ("anthropic/claude-sonnet-4.5", "OpenRouterAPI"),
        ("openai/gpt-4.1", "OpenRouterAPI"),
        ("openrouter/auto", "OpenRouterAPI"),
    ],
)
def test_cli_deduces_provider_and_resolves_templates(tmp_path, monkeypatch, model, provider_name):
    from codes import workflow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "TEMPLATE_ROOT", tmp_path / "missing")
    provider = ScriptedProvider(responses())
    options = {}

    def make_provider(**kwargs):
        options.update(kwargs)
        return provider

    monkeypatch.setattr(workflow, provider_name, make_provider)
    (tmp_path / "paper.json").write_text('{"title": "CLI paper"}')
    args = [
        "paper.json",
        "--output-dir",
        "artifacts",
        "--output-repo-dir",
        "repo",
    ]
    if model is not None:
        args += ["--model", model]
    workflow.main(args)
    assert (tmp_path / "repo/main.py").read_text() == "from src.model import Model\n"
    assert options["timeout"] == 600
    if provider_name == "OpenRouterAPI":
        assert options["model"] == model
    else:
        assert "model" not in options  # CLI aliases use the CLI's configured model.
    assert all("CLI paper" in context for context in provider.contexts[:4])


def test_unknown_model_alias_is_rejected_before_reading_paper(capsys):
    from codes.workflow import main

    with pytest.raises(SystemExit) as error:
        main(["missing.json", "--model", "cluade"])
    assert error.value.code == 2
    assert "OpenRouter" in capsys.readouterr().err


@pytest.mark.parametrize("model", ["codex", "claude"])
def test_cli_providers_run_the_workflow_through_their_process_boundary(
    tmp_path, monkeypatch, model
):
    from slick.providers import Command

    from codes.workflow import main

    provider = ScriptedProvider(responses())
    commands = []

    async def run_process(self, command, prompt, *, workdir):
        commands.append(command)
        text, _ = await provider.acall(prompt)
        if model == "codex":
            return (
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": text},
                    }
                )
                + "\n"
            )
        return text

    monkeypatch.setattr(Command, "_arun_process", run_process)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.tex").write_text(
        "The full paper must remain available to every planning call."
    )
    main(["paper.tex", "--model", model, "--output-dir", "artifacts", "--output-repo-dir", "repo"])
    assert (tmp_path / "repo/main.py").read_text() == "from src.model import Model\n"
    assert len(commands) == 8
    assert all("The full paper" in context for context in provider.contexts[:4])
    command = commands[0]
    assert command[0] == model
    assert "--model" not in command
    if model == "codex":
        assert command[1:3] == ["exec", "--json"]
        assert command[command.index("--sandbox") + 1] == "read-only"
    else:
        assert command[command.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in command
        assert command[command.index("--permission-mode") + 1] == "dontAsk"
