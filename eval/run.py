"""Freeze an executable baseline without copying outputs or credentials."""

import hashlib
import json
import subprocess
from pathlib import Path


def snapshot_baseline(destination: Path, *, source: Path | None = None) -> dict[str, str]:
    source = source or Path(__file__).resolve().parents[1]
    names = {"pyproject.toml", "uv.lock", "requirements.txt", ".python-version"}
    names.update(
        str(path.relative_to(source))
        for pattern in ("*.py", "*.j2")
        for path in (source / "codes").rglob(pattern)
    )
    contents = {}
    for name in sorted(names):
        path = source / name
        if any(part.is_symlink() for part in [path, *path.parents] if part != source.parent):
            raise ValueError(f"Cannot snapshot symlink: {name}")
        if path.is_file():
            contents[name] = path.read_bytes()
    revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    files = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in contents.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        "revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "files": files,
        "experimental_changes": ["typed design/task JSON healer"],
        "source_hash": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return files


async def calibrate(destination: Path, image: str, *, executor=None) -> dict:
    """Six Docker checks; only semantic failures count as fault rejection."""
    from codes.contracts import CheckSpec
    from codes.execution import materialize_snapshot, run_check

    executor = executor or run_check
    root = Path(__file__).parent
    destination.mkdir(parents=True, exist_ok=False)
    reference = {p.name: p.read_text() for p in (root / "fixtures/reference").glob("*.py")}
    suite = root / "acceptance/controls"
    cases = [
        ("constant", "location.py", "test_nonconstant_anchor"),
        ("annualization", "dispersion.py", "test_annualization_convention"),
        ("train_only", "scaling.py", "test_full_period_scaling"),
    ]
    results = []
    for name, module, target in cases:
        outcomes = []
        for variant in ("reference", "fault"):
            files = dict(reference)
            if variant == "fault":
                files[module] = (root / f"fixtures/faults/{name}.py").read_text()
            workspace = destination / name / variant
            materialize_snapshot(workspace, files)
            result = await executor(
                CheckSpec(
                    id=f"{name}-{variant}",
                    kind="pytest",
                    targets=[f"tests/acceptance/controls/test_controls.py::{target}"],
                ),
                workspace,
                suite,
                image,
                evidence_dir=destination / name / (variant + "-check"),
            )
            outcomes.append(result.model_dump())
        results.append({"case": name, "reference": outcomes[0], "fault": outcomes[1]})
    report = {
        "pairs": len(results),
        "reference_passed": sum(r["reference"]["status"] == "passed" for r in results),
        "faults_rejected": sum(r["fault"]["status"] == "failed" for r in results),
        "false_acceptances": sum(r["fault"]["status"] == "passed" for r in results),
        "false_rejections": sum(r["reference"]["status"] == "failed" for r in results),
        "inconclusive": sum(
            r[v]["status"] not in {"passed", "failed"}
            for r in results
            for v in ("reference", "fault")
        ),
        "human_adjudication": "pending",
        "results": results,
    }
    (destination / "calibration.json").write_text(json.dumps(report, indent=2))
    return report


def evaluate(
    stage: str,
    destination: Path,
    *,
    image: tuple[str, str],
    paper: Path | None = None,
    previous: Path | None = None,
    baseline: Path | None = None,
    workflow=None,
) -> dict:
    import asyncio
    import time

    from codes.contracts import CheckSpec
    from codes.execution import materialize_snapshot, run_check, tree_hash
    from codes.store import digest
    from codes.workflow import main

    budgets = {"micro": (30, 900), "component": (60, 1800), "full": (120, 3600)}
    calls, seconds = budgets[stage]
    if stage != "micro":
        if previous is None:
            raise ValueError("A passing previous stage report is required")
        prior = json.loads(previous.read_text())
        if (
            prior["stage"] != ("micro" if stage == "component" else "component")
            or prior["outcome"] != "complete"
        ):
            raise ValueError("The previous stage must pass before promotion")
        if paper is None:
            raise ValueError("Specify --paper for the component/full stage")
    paper = paper or Path(__file__).parent / "fixtures/micro.md"
    original = paper.read_bytes()
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    baseline_hash = digest(baseline.read_bytes()) if baseline else None
    # Freeze external tests before generation; never include their text in model packets.
    external = Path(__file__).parent / "acceptance/holdout"
    suite = root / "external"
    files = (
        {p.relative_to(external).as_posix(): p.read_text() for p in external.rglob("*.py")}
        if stage == "micro"
        else {}
    )
    materialize_snapshot(suite, files)
    started = time.monotonic()
    report = {
        "stage": stage,
        "paper_hash": digest(original),
        "acceptance_hash": tree_hash(suite),
        "baseline_manifest_hash": baseline_hash,
        "model": "openai/gpt-oss-120b:nitro",
        "image_id": image[0],
        "platform": image[1],
        "outcome": "failed",
        "calls_reserved": 0,
        "measured_cost": None,
        "external_check": None,
        "human_adjudication": "pending",
    }
    (root / "evaluation.json").write_text(json.dumps(report, indent=2))
    try:
        code = (workflow or main)(
            [
                str(paper),
                "--model",
                report["model"],
                "--executor-image",
                image[0],
                "--output-dir",
                str(root / "run"),
                "--output-repo-dir",
                str(root / "repo"),
                "--max-calls",
                str(calls),
                "--run-timeout",
                str(seconds),
            ]
        )
        if (root / "run/report.json").exists():
            run = json.loads((root / "run/report.json").read_text())
            report.update(
                outcome=run["outcome"],
                workflow_outcome=run["outcome"],
                calls_reserved=run["calls_reserved"],
                measured_cost=run["measured_cost"],
            )
        if code == 0 and stage == "micro":
            result = asyncio.run(
                run_check(
                    CheckSpec(
                        id="external",
                        kind="pytest",
                        targets=["tests/acceptance/holdout/test_micro.py::test_method"],
                    ),
                    root / "repo",
                    suite,
                    image[0],
                    evidence_dir=root / "external-check",
                )
            )
            report["external_check"] = result.model_dump()
            report["outcome"] = "complete" if result.status == "passed" else "failed"
        elif code != 0 and report["outcome"] == "complete":
            report["outcome"] = "failed"
    except KeyboardInterrupt:
        report["outcome"] = "cancelled"
        raise
    finally:
        report["wall_seconds"] = time.monotonic() - started
        (root / "evaluation.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv=None):
    import argparse
    import asyncio

    from codes.workflow import executor_image

    parser = argparse.ArgumentParser(description="Frozen Paper2Code evaluation stages")
    parser.add_argument("action", choices=["calibrate", "run"])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=["micro", "component", "full"], default="micro")
    parser.add_argument("--paper", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--executor-image", default="paper2code-executor:local")
    args = parser.parse_args(argv)
    image = executor_image(args.executor_image)
    if args.action == "calibrate":
        report = asyncio.run(calibrate(args.output_dir, image[0]))
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
        return int(
            report["faults_rejected"] != report["pairs"]
            or report["reference_passed"] != report["pairs"]
        )
    report = evaluate(
        args.stage,
        args.output_dir,
        image=image,
        paper=args.paper,
        previous=args.previous,
        baseline=args.baseline,
    )
    print(f"{report['outcome']}: {args.output_dir / 'evaluation.json'}")
    return int(report["outcome"] != "complete")


if __name__ == "__main__":
    raise SystemExit(main())
