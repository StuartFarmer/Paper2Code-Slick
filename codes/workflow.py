"""Reproduce a paper through planning, per-file analysis, and sequential coding."""

import argparse
import asyncio
import json
import re
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field
from slick import Session, prompt, prompts, workflow
from slick.providers import ClaudeCLI, CodexCLI, OpenRouterAPI, Provider

from .paper import load_paper


class Tasks(BaseModel):
    files: list[str] = Field(alias="Task list", min_length=1)
    descriptions: list[tuple[str, str]] = Field(alias="Logic Analysis")


def parse_content(text: str) -> dict:
    """Parse the JSON contract inside the paper's response delimiters."""
    return json.loads(text.strip().removeprefix("[CONTENT]").removesuffix("[/CONTENT]"))


def output_path(root: Path, filename: str) -> Path:
    """Confine model-supplied paths, including existing symlinks, to the output root."""
    relative = PurePosixPath(filename)
    if (
        not filename
        or relative.is_absolute()
        or "\\" in filename
        or any(part in ("", ".", "..") or part.startswith(".") for part in filename.split("/"))
    ):
        raise ValueError(f"Unsafe generated filename: {filename!r}")
    target = root / filename
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Generated filename escapes output directory: {filename!r}")
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Generated filename follows a symlink: {filename!r}")
        current = current.parent
    return target


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PaperCoder:
    """One run per instance; no generation retries or execution of generated code.

    Planning shares a Session. Analysis and coding each use fresh sessions.
    Raw exchanges survive validation failures; existing output files are replaced.
    Configure slick.prompts.TEMPLATE_ROOT before starting the workflow.
    """

    def __init__(
        self,
        paper: str,
        paper_format: str,
        provider: Provider,
        output_dir: Path,
        output_repo_dir: Path,
    ):
        self.paper = paper
        self.paper_format = paper_format
        self.provider = provider
        self.output_dir = output_dir
        self.output_repo_dir = output_repo_dir

    @prompt(template="overview.j2", max_turns=1)
    async def plan_overview(self) -> str:
        """Outline the reproduction strategy."""

    @prompt(template="design.j2", max_turns=1)
    async def plan_design(self) -> str:
        """Design the files and interfaces."""

    @prompt(template="tasks.j2", max_turns=1)
    async def plan_tasks(self) -> str:
        """Order files by their dependencies."""

    @prompt(template="config.j2", max_turns=1)
    async def plan_config(self) -> str:
        """Extract the paper's configuration."""

    @prompt(template="analyze.j2", max_turns=1)
    async def analyze_file(self, filename: str, draft_desc: str) -> str:
        """Analyze one file independently."""

    @prompt(template="code.j2", max_turns=1)
    async def code_file(
        self,
        filename: str,
        analysis: str,
        code_files: str,
        done_file_lst: list[str],
    ) -> str:
        """Implement one file with previously generated code in context."""

    @workflow
    async def run(self) -> Path:
        await self.plan()
        analyses = await self.analyze()
        await self.code(analyses)
        return self.output_repo_dir

    async def plan(self) -> None:
        session = Session(provider=self.provider)
        self.overview = await self._invoke(self.plan_overview, session=session, record="planning")
        self.design = await self._invoke(self.plan_design, session=session, record="planning")
        self.tasks_text = await self._invoke(self.plan_tasks, session=session, record="planning")
        tasks_data = parse_content(self.tasks_text)
        tasks = Tasks.model_validate(tasks_data)
        if len(set(tasks.files)) != len(tasks.files):
            raise ValueError("Duplicate files in generated task list")
        self.files = [name for name in tasks.files if name != "config.yaml"]
        self.descriptions = dict(tasks.descriptions)
        for name in ["config.yaml", *self.files]:
            output_path(self.output_repo_dir, name)
            output_path(self.output_dir / "analysis", name + ".txt")
        raw = await self._invoke(self.plan_config, session=session, record="planning")
        match = re.search(r"```yaml\s*\n(.*?)\n```", raw, re.DOTALL)
        if not match or not match[1].strip():
            raise ValueError("Configuration response must contain a nonempty YAML code block")
        self.config = match[1] + "\n"
        write_text(output_path(self.output_repo_dir, "config.yaml"), self.config)
        artifacts = self.output_dir / "planning"
        for name, text in [
            ("overview.txt", self.overview),
            ("design.json", json.dumps(parse_content(self.design), indent=2)),
            ("tasks.json", json.dumps(tasks_data, indent=2)),
            ("config.yaml", self.config),
        ]:
            write_text(artifacts / name, text)

    async def analyze(self) -> dict[str, str]:
        analyses = {}
        for filename in self.files:
            description = self.descriptions.get(filename, "")
            draft = f"Write the logic analysis in '{filename}'."
            if description.strip():
                draft = f"Write the logic analysis in '{filename}', which is intended for '{description}'."
            analyses[filename] = await self._invoke(
                self.analyze_file,
                filename,
                draft,
                record=f"analysis/{filename}",
            )
            path = output_path(
                self.output_dir / "analysis",
                filename + ".txt",
            )
            write_text(path, analyses[filename])
        return analyses

    async def code(self, analyses: dict[str, str]) -> None:
        written = {}
        for filename in self.files:
            code_files = "".join(
                f"\n```python\n{code}\n```\n\n"
                for name, code in written.items()
                if not name.endswith(".yaml")
            )
            raw = await self._invoke(
                self.code_file,
                filename,
                analyses[filename],
                code_files,
                ["config.yaml", *written],
                record=f"coding/{filename}",
            )
            match = re.search(r"^```(?:\w+)?\s*\n(.*?)(?=^```)```", raw, re.DOTALL | re.MULTILINE)
            code = match[1] if match and match[1] else raw
            write_text(output_path(self.output_repo_dir, filename), code)
            written[filename] = code

    async def _invoke(self, operation, *args, record: str, session: Session | None = None) -> str:
        session = session or Session(provider=self.provider)
        print(f"{operation.__name__}: {args[0] if args else 'paper'}", flush=True)
        try:
            text = await operation(*args, session=session)
            text = text.split("</think>")[-1]
            if not text.strip():
                raise ValueError("Model returned an empty response")
            return text
        except Exception as error:
            write_text(
                self.output_dir / "failure.json",
                json.dumps(
                    {
                        "operation": operation.__name__,
                        "record": record,
                        "error": f"{type(error).__name__}: {error}",
                    },
                    indent=2,
                ),
            )
            raise
        finally:
            # Save raw text before downstream parsing, including rejected responses.
            write_text(
                output_path(self.output_dir / "calls", f"{record}.json"),
                json.dumps(session.history, indent=2),
            )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper", type=Path, help="PDF extraction JSON, Markdown, or LaTeX source")
    parser.add_argument(
        "--model",
        default="codex",
        help="codex (default), claude, or an OpenRouter model ID such as anthropic/claude-sonnet-4.5",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/Transformer"))
    parser.add_argument("--output-repo-dir", type=Path, default=Path("outputs/Transformer_repo"))
    args = parser.parse_args(argv)
    if args.model == "codex":
        provider = CodexCLI(timeout=600)
    elif args.model == "claude":
        provider = ClaudeCLI(
            command='claude -p --output-format text --tools "" --strict-mcp-config --permission-mode dontAsk',
            timeout=600,
        )
    elif "/" in args.model:
        provider = OpenRouterAPI(model=args.model, timeout=600, max_output_tokens=32768)
    else:
        parser.error("--model must be codex, claude, or an OpenRouter model ID (provider/model)")
    prompts.TEMPLATE_ROOT = Path(__file__).resolve().parent / "prompts"
    paper, paper_format = load_paper(args.paper)
    coder = PaperCoder(paper, paper_format, provider, args.output_dir, args.output_repo_dir)
    print(f"Repository saved to {asyncio.run(coder.run())}")


if __name__ == "__main__":
    main()
