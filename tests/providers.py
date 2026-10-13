class ScriptedProvider:
    """Return canned model text while retaining the actual rendered requests."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    async def acall(self, context, *, tools=None, tool_results=None):
        self.contexts.append(context)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response, []


class ScriptedExecutor:
    """Offline controller tests only; real executor checks live in Docker tests."""

    def __init__(self, statuses=()):
        self.statuses = iter(statuses)
        self.calls = []

    async def __call__(self, check, workspace, suite, image, **kwargs):
        from pathlib import Path

        from codes.contracts import ExecutionResult
        from codes.execution import tree_hash

        self.calls.append(check)
        status = next(self.statuses, "passed")
        evidence = Path(kwargs["evidence_dir"])
        evidence.mkdir(parents=True, exist_ok=False)
        (evidence / "stdout.txt").write_text(
            "NotImplementedError: contract scaffold" if status == "failed" else "scripted result"
        )
        (evidence / "stderr.txt").write_text("")
        return ExecutionResult(
            check_id=check.id,
            candidate_hash=tree_hash(workspace),
            dependency_hash=kwargs.get("dependency_hash", ""),
            suite_hash=tree_hash(suite),
            image_id=image,
            argv=["scripted", check.kind],
            exit_code=0 if status == "passed" else 1,
            status=status,
            duration_seconds=0,
            stdout_artifact=str(evidence / "stdout.txt"),
            stderr_artifact=str(evidence / "stderr.txt"),
            output_truncated=False,
            collected_tests=len(check.targets) if check.kind in {"pytest", "smoke"} else None,
        )
