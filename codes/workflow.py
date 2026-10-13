"""Generate and verify a paper implementation using bounded OpenRouter calls."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from importlib.metadata import version
from pathlib import Path

from slick import prompts
from slick.providers import OpenRouterAPI

from .agent import OPERATIONS, PaperCoder, run_verified
from .contracts import Limits, RunManifest
from .execution import cleanup_run, run_check
from .paper import Excerpt, PaperIndex, index_paper
from .store import RunStore, digest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "openai/gpt-oss-120b:nitro"


def executor_image(name: str) -> tuple[str, str]:
    result = subprocess.run(
        ["docker", "image", "inspect", name], capture_output=True, text=True, timeout=30, check=True
    )
    info = json.loads(result.stdout)[0]
    return info["Id"], info["Os"] + "/" + info["Architecture"]


def inputs(original: bytes) -> dict[str, str]:
    paths = [
        *sorted((ROOT / "codes").rglob("*.py")),
        *sorted((ROOT / "codes/prompts/improved").glob("*.j2")),
        ROOT / "uv.lock",
        ROOT / "docker/requirements.lock",
        ROOT / "docker/check.py",
        ROOT / "docker/Dockerfile",
    ]
    hashes = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths}
    hashes["paper"] = digest(original)
    hashes["runtime"] = digest(
        json.dumps(
            {p: version(p) for p in ("slick-ai", "pydantic", "Jinja2")}, sort_keys=True
        ).encode()
    )
    return hashes


async def preflight_templates(coder: PaperCoder) -> None:
    for name in [*OPERATIONS, "repair_schema"]:
        await getattr(coder, name).render(coder, {})


def restored_index(store: RunStore) -> PaperIndex:
    fields = json.loads(store.read_artifact("source/index.json"))
    fields["locations"] = {int(k): v for k, v in fields["locations"].items()}
    fields["excerpts"] = [Excerpt(**e) for e in fields["excerpts"]]
    return PaperIndex(original=store.read_artifact("source/original.txt").encode(), **fields)


def run(store: RunStore, index: PaperIndex) -> int:
    templates = ROOT / "codes/prompts/improved"
    for path in sorted(templates.glob("*.j2")):
        name = "prompts/improved/" + path.name
        if name not in store.artifacts:
            store.save_artifact(name, path.read_text())
    prompts.TEMPLATE_ROOT = store.root / "prompts"
    limits = store.manifest.limits
    providers = {
        role: OpenRouterAPI(
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
        reviewer=providers["reviewer"],
        executor=run_check,
    )
    asyncio.run(preflight_templates(coder))
    if store.manifest.outcome != "complete" and not os.environ.get("OPENROUTER_API_KEY"):
        raise ValueError("Set OPENROUTER_API_KEY before starting or resuming an incomplete run")
    output = asyncio.run(run_verified(coder, index))
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
    parser.add_argument("--model", help=f"OpenRouter provider/model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--planner-model")
    parser.add_argument("--reviewer-model")
    parser.add_argument(
        "--executor-image", help="Locally built Docker image (default: paper2code-executor:local)"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--output-repo-dir", type=Path)
    for flag in ("concurrency", "test-concurrency", "max-calls", "run-timeout"):
        parser.add_argument("--" + flag, type=int)
    args = parser.parse_args(argv)
    if args.resume and any(v is not None for k, v in vars(args).items() if k != "resume"):
        parser.error("--resume cannot be combined with a paper or new-run settings")
    if not args.resume and not args.paper:
        parser.error("Provide a paper or --resume RUN_DIRECTORY")
    for model in (args.model, args.planner_model, args.reviewer_model):
        if model is not None and (
            "/" not in model or not all(model.split("/", 1)) or any(c.isspace() for c in model)
        ):
            parser.error(
                "Verified V1 requires an OpenRouter provider/model ID; codex and claude CLI aliases are unsupported"
            )
    try:
        if args.resume:
            with RunStore.open(args.resume) as store:
                index = restored_index(store)
                if inputs(index.original) != store.manifest.input_hashes:
                    raise ValueError(
                        "Source code, prompts, or dependencies changed; create a new run"
                    )
                image_id, platform = executor_image(store.manifest.image_id)
                if (image_id, platform) != (store.manifest.image_id, store.manifest.platform):
                    raise ValueError("Executor changed; create a new run")
                cleanup_run(store.manifest.run_id)
                return run(store, index)
        index = index_paper(args.paper)
        root = (args.output_dir or Path("outputs/Transformer")).resolve()
        repo = (args.output_repo_dir or Path("outputs/Transformer_repo")).resolve()
        if root == repo or root in repo.parents or repo in root.parents:
            raise ValueError("Run and export directories must be distinct and not nested")
        if root.exists() or repo.exists():
            raise FileExistsError("Use unused output directories, or --resume for an existing run")
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise ValueError("Set OPENROUTER_API_KEY before starting a run")
        limits = Limits(
            **{k: v for k, v in vars(args).items() if k in Limits.model_fields and v is not None}
        )
        image_id, platform = executor_image(args.executor_image or "paper2code-executor:local")
        model = args.model or DEFAULT_MODEL
        manifest = RunManifest(
            run_id=uuid.uuid4().hex,
            input_hashes=inputs(index.original),
            image_id=image_id,
            platform=platform,
            models={
                "worker": model,
                "planner": args.planner_model or model,
                "reviewer": args.reviewer_model or model,
            },
            output_repo=str(repo),
            limits=limits,
        )
        with RunStore.create(root, manifest) as store:
            return run(store, index)
    except KeyboardInterrupt:
        print("Cancelled; evidence retained. Resume with --resume RUN_DIRECTORY.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Paper2Code: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
