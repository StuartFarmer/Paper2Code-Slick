"""Plan, generate, test and repair a paper implementation with Slick."""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from importlib.metadata import version
from pathlib import Path

from slick import prompts
from slick.providers import CodexCLI, OpenRouterAPI

from .agent import OPERATIONS, PaperCoder, run_workflow
from .contracts import Limits, RunManifest
from .execution import cleanup_run, run_check
from .paper import load_paper
from .store import RunStore, digest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "openai/gpt-oss-120b:nitro"


def executor_image(name: str) -> tuple[str, str]:
    result = subprocess.run(
        ["docker", "image", "inspect", name], capture_output=True, text=True, timeout=30, check=True
    )
    info = json.loads(result.stdout)[0]
    return info["Id"], info["Os"] + "/" + info["Architecture"]


def inputs(original: bytes, paper: str) -> dict[str, str]:
    paths = [
        *sorted((ROOT / "codes").rglob("*.py")),
        *sorted((ROOT / "codes/prompts/simple").glob("*.j2")),
        ROOT / "uv.lock",
        ROOT / "docker/requirements.lock",
        ROOT / "docker/check.py",
        ROOT / "docker/Dockerfile",
    ]
    hashes = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths}
    hashes["paper"] = digest(original)
    hashes["paper_text"] = digest(paper.encode())
    hashes["runtime"] = digest(
        json.dumps(
            {p: version(p) for p in ("slick-ai", "pydantic", "Jinja2")}, sort_keys=True
        ).encode()
    )
    return hashes


async def preflight_templates(coder: PaperCoder) -> None:
    for name in [*OPERATIONS, "repair_json"]:
        await getattr(coder, name).render(coder, {})


def check_backends(models: dict[str, str]) -> None:
    if any(model != "codex" for model in models.values()) and not os.environ.get(
        "OPENROUTER_API_KEY"
    ):
        raise ValueError("Set OPENROUTER_API_KEY for OpenRouter models")
    if "codex" in models.values() and shutil.which("codex") is None:
        raise ValueError("Codex CLI is not on PATH. Install it and run `codex login` first")


def run(store: RunStore, paper: str) -> int:
    check_backends(store.manifest.models)
    templates = ROOT / "codes/prompts/simple"
    for path in sorted(templates.glob("*.j2")):
        name = "prompts/simple/" + path.name
        if name not in store.artifacts:
            store.save_artifact(name, path.read_text())
    prompts.TEMPLATE_ROOT = store.root / "prompts"
    limits = store.manifest.limits
    providers = {
        role: CodexCLI(
            command="codex --disable shell_tool --disable unified_exec",
            timeout=limits.call_timeout,
            workdir=ROOT,
        )
        if model == "codex"
        else OpenRouterAPI(
            model=model,
            timeout=limits.call_timeout,
            max_output_tokens=limits.output_tokens,
            max_retries=0,
        )
        for role, model in store.manifest.models.items()
    }
    coder = PaperCoder(
        store,
        providers["worker"],
        planner=providers["planner"],
        executor=run_check,
    )
    asyncio.run(preflight_templates(coder))
    output = asyncio.run(run_workflow(coder, paper))
    print(f"Report: {store.root / 'report.md'}")
    if output:
        print(f"Repository saved to {output} ({store.manifest.outcome})")
        return 0 if store.manifest.outcome in {"complete", "draft"} else 1
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper", nargs="?", type=Path, help="JSON, Markdown, or LaTeX source")
    parser.add_argument(
        "--resume", type=Path, help="Resume a frozen run without overriding its settings"
    )
    parser.add_argument(
        "--model", help=f"codex or OpenRouter provider/model ID (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--planner-model", help="Override planning and test-writing model; defaults to --model"
    )
    parser.add_argument(
        "--executor-image", help="Locally built Docker image (default: paper2code-executor:local)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Run folder (default: unused outputs/<arXiv folder or paper stem>)",
    )
    parser.add_argument(
        "--output-repo-dir", type=Path, help="Export folder (default: <run folder>/repo)"
    )
    for flag in ("concurrency", "max-calls", "run-timeout"):
        parser.add_argument("--" + flag, type=int)
    args = parser.parse_args(argv)
    if args.resume and any(v is not None for k, v in vars(args).items() if k != "resume"):
        parser.error("--resume cannot be combined with a paper or new-run settings")
    if not args.resume and not args.paper:
        parser.error("Provide a paper or --resume RUN_DIRECTORY")
    for model in (args.model, args.planner_model):
        if (
            model is not None
            and model != "codex"
            and (
                "/" not in model or not all(model.split("/", 1)) or any(c.isspace() for c in model)
            )
        ):
            parser.error("Use codex or an OpenRouter provider/model ID")
    try:
        if args.resume:
            with RunStore.open(args.resume) as store:
                paper = store.read_artifact("source/paper.txt")
                original = store.read_artifact("source/original.txt").encode()
                if inputs(original, paper) != store.manifest.input_hashes:
                    raise ValueError(
                        "Source code, prompts, or dependencies changed; create a new run"
                    )
                image_id, platform = executor_image(store.manifest.image_id)
                if (image_id, platform) != (store.manifest.image_id, store.manifest.platform):
                    raise ValueError("Executor changed; create a new run")
                cleanup_run(store.manifest.run_id)
                if store.manifest.outcome == "complete":
                    print(f"Repository saved to {store.manifest.export_path} (complete)")
                    return 0
                return run(store, paper)
        paper, _ = load_paper(args.paper)
        original = args.paper.read_bytes()
        if not paper.strip():
            raise ValueError("Paper contains no text")
        paper_name = next(
            (
                parent.name
                for parent in args.paper.resolve().parents
                if parent.name.lower().startswith("arxiv-")
            ),
            args.paper.stem,
        )
        root = (args.output_dir or Path("outputs") / paper_name).resolve()
        if args.output_dir is None:
            base = root
            number = 2
            while root.exists() or root.is_symlink():
                root = base.with_name(f"{base.name}-{number}")
                number += 1
        repo = (args.output_repo_dir or root / "repo").resolve()
        if root == repo or repo in root.parents:
            raise ValueError("Export directory must not overlap or contain the run directory")
        if root in repo.parents and repo.relative_to(root).parts[0] in {
            "manifest.json",
            "artifacts.json",
            "run.lock",
            "state.json",
            "events.jsonl",
            "source",
            "prompts",
            "calls",
            "generated",
            "repairs",
            "snapshots",
            "suite",
            "checks",
            "exports",
            "notebooks",
            "plan.json",
            "tests.py",
            "report.json",
            "report.md",
        }:
            raise ValueError("Export directory overlaps run state; use <run directory>/repo")
        if root.exists() or repo.exists():
            raise FileExistsError(
                "Output already exists. Omit output flags to choose a fresh folder, "
                "or use --resume RUN_DIRECTORY"
            )
        model = args.model or DEFAULT_MODEL
        models = {"worker": model, "planner": args.planner_model or model}
        check_backends(models)
        limits = Limits(
            **{k: v for k, v in vars(args).items() if k in Limits.model_fields and v is not None}
        )
        image_id, platform = executor_image(args.executor_image or "paper2code-executor:local")
        manifest = RunManifest(
            run_id=uuid.uuid4().hex,
            input_hashes=inputs(original, paper),
            image_id=image_id,
            platform=platform,
            models=models,
            output_repo=str(repo),
            limits=limits,
        )
        with RunStore.create(root, manifest) as store:
            store.save_artifact("source/paper.txt", paper)
            store.save_artifact("source/original.txt", original.decode())
            print(f"Run: {root}\nRepository: {repo}", flush=True)
            return run(store, paper)
    except KeyboardInterrupt:
        print("Cancelled; evidence retained. Resume with --resume RUN_DIRECTORY.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Paper2Code: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
