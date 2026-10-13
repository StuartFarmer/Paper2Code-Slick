"""Stage confined snapshots and run fixed checks inside disposable Docker containers."""

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from .contracts import Candidate, CheckSpec, ExecutionResult, RunnerReport, TaskSpec
from .store import digest
from .workflow import output_path

LOG_LIMIT = 1024 * 1024


def tree_hash(root: Path) -> str:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink in snapshot: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return digest(json.dumps(files, sort_keys=True).encode())


def stage_candidate(
    task: TaskSpec,
    candidate: Candidate,
    workspace: Path,
    *,
    dependencies: dict[str, str] | None = None,
) -> str:
    files = {f.path: f.content for f in candidate.files}
    if len(files) != len(candidate.files) or set(files) != set(task.owned_paths):
        raise ValueError("Candidate must supply exactly its owned files")
    if (
        any(len(c.encode()) > 16384 for c in files.values())
        or sum(len(c.encode()) for c in files.values()) > 32768
    ):
        raise ValueError("Candidate exceeds file/bundle byte budget")
    dependencies = dependencies or {}
    if files.keys() & dependencies.keys():
        raise ValueError("Candidate overlaps dependency files")
    files = {**dependencies, **files}
    for name in files:
        output_path(workspace, name)
    workspace.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        path = output_path(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tree_hash(workspace)


def docker_argv(check: CheckSpec, workspace: Path, suite: Path, image: str, name: str) -> list[str]:
    if not image.startswith("sha256:"):
        raise ValueError("Execution requires a resolved immutable image ID")
    for target in check.targets:
        if check.kind == "imports":
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", target):
                raise ValueError("Invalid import target")
        else:
            path = target.split("::")[0]
            output_path(Path("/targets"), path)
            if not path.endswith(".py"):
                raise ValueError("Only Python check targets are supported")
            if check.kind in {"pytest", "smoke"} and (
                not path.startswith("tests/acceptance/") or "::" not in target
            ):
                raise ValueError("Acceptance checks require registered node IDs")
    for path in (workspace, suite):
        if "," in str(path):
            raise ValueError("Docker bind mount paths cannot contain commas")
    return [
        "docker",
        "run",
        "--name",
        name,
        "--label",
        "paper2code.executor=true",
        "--init",
        "--user",
        "65534:65534",
        "--read-only",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--cpus",
        "1",
        "--memory",
        "2g",
        "--memory-swap",
        "2g",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,size=256m",
        "--mount",
        f"type=bind,src={workspace.resolve()},dst=/workspace,readonly",
        "--mount",
        f"type=bind,src={suite.resolve()},dst=/acceptance,readonly",
        "--workdir",
        "/workspace",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
        "--env",
        "OPENBLAS_NUM_THREADS=1",
        "--env",
        "OMP_NUM_THREADS=1",
        "--env",
        "MKL_NUM_THREADS=1",
        image,
        "python",
        "/runner/check.py",
        check.model_dump_json(),
    ]


def parse_report(output: str, check: CheckSpec) -> dict:
    reports = [
        line[len("P2C_RESULT=") :] for line in output.splitlines() if line.startswith("P2C_RESULT=")
    ]
    if len(reports) != 1:
        raise ValueError("Missing or duplicate runner report")
    result = RunnerReport.model_validate_json(reports[0]).model_dump()
    if result["kind"] != check.kind or result["targets"] != check.targets:
        raise ValueError("Runner report does not match registered check")
    if check.kind in {"pytest", "smoke"}:
        if not result["collected"] or not all(
            any(n == t or n.startswith(t + "[") for n in result["collected"]) for t in check.targets
        ):
            raise ValueError("Required tests were not collected")
        if result["exit_code"] == 0 and (
            result["failed"]
            or result["skipped"]
            or result["errors"]
            or set(result["collected"]) != set(result["passed"])
        ):
            raise ValueError("False passing test report")
    return result


async def run_check(
    check: CheckSpec,
    workspace: Path,
    suite: Path,
    image: str,
    *,
    evidence_dir: Path | None = None,
    dependency_hash: str = "",
) -> ExecutionResult:
    name = "p2c-" + uuid.uuid4().hex
    argv = docker_argv(check, workspace, suite, image, name)
    candidate_hash, suite_hash = tree_hash(workspace), tree_hash(suite)
    evidence_dir = evidence_dir or workspace.parent / "checks" / name
    evidence_dir.mkdir(parents=True, exist_ok=False)
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT")
        if key in os.environ
    }
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )

    async def drain(stream, path):
        size, tail = 0, b""
        with path.open("wb") as output:
            while chunk := await stream.read(65536):
                output.write(chunk[: max(0, LOG_LIMIT - size)])
                size += len(chunk)
                tail = (tail + chunk)[-65536:]
        return size > LOG_LIMIT, tail.decode("utf-8", errors="replace")

    stdout_path, stderr_path = evidence_dir / "stdout.txt", evidence_dir / "stderr.txt"
    drains = [
        asyncio.create_task(drain(process.stdout, stdout_path)),
        asyncio.create_task(drain(process.stderr, stderr_path)),
    ]
    status, result, cancelled = "infrastructure_error", {}, False

    async def control(*args):
        command = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            out, _ = await asyncio.wait_for(command.communicate(), timeout=30)
            return command.returncode, out
        finally:
            if command.returncode is None:
                command.kill()
                await command.wait()

    try:
        await asyncio.wait_for(process.wait(), check.timeout_seconds)
        _, state = await control("inspect", "--format", "{{json .State}}", name)
        oom = json.loads(state or b"{}").get("OOMKilled", False)
        if oom:
            status = "oom"
        else:
            stdout_result, _ = await asyncio.gather(*drains)
            try:
                result = parse_report(stdout_result[1], check)
                status = "passed" if process.returncode == result["exit_code"] == 0 else "failed"
                if result.get("errors"):
                    status = "infrastructure_error"
            except (ValueError, TypeError):
                status = "infrastructure_error"
    except asyncio.TimeoutError:
        status = "timeout"
    except asyncio.CancelledError:
        status, cancelled = "cancelled", True
    finally:
        await asyncio.shield(control("rm", "--force", name))
        if process.returncode is None:
            process.kill()
        await process.wait()
        drained = await asyncio.gather(*drains)
    truncated = any(item[0] for item in drained)
    outcome = ExecutionResult(
        check_id=check.id,
        candidate_hash=candidate_hash,
        dependency_hash=dependency_hash,
        suite_hash=suite_hash,
        image_id=image,
        argv=argv,
        exit_code=process.returncode,
        status=status,
        duration_seconds=time.monotonic() - started,
        stdout_artifact=str(stdout_path),
        stderr_artifact=str(stderr_path),
        output_truncated=truncated,
        collected_tests=len(result["collected"]) if "collected" in result else None,
        property_statistics=result.get("property_statistics", {}),
        replay_complete=not truncated,
    )
    (evidence_dir / "result.json").write_text(outcome.model_dump_json(indent=2))
    if cancelled:
        raise asyncio.CancelledError
    return outcome
