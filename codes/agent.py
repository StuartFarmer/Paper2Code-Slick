"""Plan files, write them in parallel, then test and repair the repository."""

import asyncio
import json
import uuid
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from slick import Session, prompt, workflow

from .contracts import CheckSpec, Plan, Revision
from .execution import materialize_snapshot, run_check, tree_hash
from .paths import output_path
from .store import RunStore, atomic_write

TEST_FILE = "tests/acceptance/test_generated.py"
OPERATIONS = {"plan": Plan, "implement": str, "author_tests": str, "repair": Revision}


def file_text(text: str) -> str:
    """Accept a single outer Markdown fence without changing code indentation."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```") and lines[-1] == "```":
        return "\n".join(lines[1:-1]) + "\n"
    return text


class PaperCoder:
    def __init__(self, store: RunStore, provider, *, planner=None, executor=run_check):
        self.store = store
        self.providers = {"worker": provider, "planner": planner or provider}
        self.executor = executor
        self.slots = asyncio.Semaphore(store.manifest.limits.concurrency)
        self.files = {
            name.removeprefix("generated/"): store.read_artifact(name)
            for name in store.artifacts
            if name.startswith("generated/")
        }
        for name in sorted(store.artifacts):
            if name.startswith("repairs/"):
                revision = Revision.model_validate_json(store.read_artifact(name))
                self.files.update({f.path: f.content for f in revision.files})
        self.tests = store.read_artifact("tests.py") if "tests.py" in store.artifacts else ""
        self.warnings = []
        self.results = []
        self.plan_value = None
        self.verified = False

    @workflow
    async def run(self, paper: str) -> None:
        plan = await self.prepare_plan(paper)
        await self.generate(plan)
        await self.test_and_repair(paper, plan)

    async def prepare_plan(self, paper: str) -> Plan:
        if "plan.json" in self.store.artifacts:
            plan = Plan.model_validate_json(self.store.read_artifact("plan.json"))
        else:
            plan = await self.invoke("plan", {"paper": paper})
            self.store.save_artifact("plan.json", plan.model_dump_json(indent=2))
        self.plan_value = plan
        return plan

    async def generate(self, plan: Plan) -> None:
        async def write(task):
            if task.path in self.files:
                return
            content = await self.invoke(
                "implement", {"overview": plan.overview, "task": task.model_dump()}
            )
            self.store.save_artifact("generated/" + task.path, content)
            self.files[task.path] = content

        jobs = [asyncio.create_task(write(task)) for task in plan.files]
        try:
            results = await asyncio.gather(*jobs, return_exceptions=True)
        except BaseException:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            raise
        for task, result in zip(plan.files, results):
            if isinstance(result, Exception):
                self.warnings.append(f"{task.path}: {result}")
        if not self.files:
            raise RuntimeError("No files generated: " + "; ".join(self.warnings))

    async def test_and_repair(self, paper: str, plan: Plan) -> None:
        if not self.tests:
            self.tests = await self.invoke(
                "author_tests", {"paper": paper, "plan": plan.model_dump(), "files": self.files}
            )
            self.store.save_artifact("tests.py", self.tests)
        while True:
            self.results = await self.check_repository()
            if all(result.status == "passed" for result in self.results):
                self.verified = True
                return
            if self.store.manifest.fixes >= self.store.manifest.limits.code_fixes:
                self.warnings.append("Repair limit reached; see check logs for remaining failures")
                return
            failures = []
            for result in self.results:
                if result.status != "passed":
                    failures.append(
                        {
                            "status": result.status,
                            "stdout": Path(result.stdout_artifact).read_text(errors="replace")[
                                -12000:
                            ],
                            "stderr": Path(result.stderr_artifact).read_text(errors="replace")[
                                -12000:
                            ],
                        }
                    )
            self.store.manifest.fixes += 1
            self.store.save_manifest()
            revision = await self.invoke(
                "repair",
                {
                    "paper": paper,
                    "plan": plan.model_dump(),
                    "files": self.files,
                    "tests": self.tests,
                    "failures": failures,
                },
            )
            self.store.save_artifact(
                f"repairs/{self.store.manifest.fixes:03d}.json", revision.model_dump_json(indent=2)
            )
            self.files.update({f.path: f.content for f in revision.files})
            if revision.notes:
                print(revision.notes, flush=True)
            if not revision.files:
                self.warnings.append(revision.notes or "Repair returned no changes")
                return

    async def check_repository(self) -> list:
        check_id = uuid.uuid4().hex
        snapshot = self.store.root / "snapshots" / check_id
        materialize_snapshot(snapshot, self.files)
        suite = self.store.root / "suite"
        materialize_snapshot(suite, {TEST_FILE: self.tests})
        python_files = [path for path in self.files if path.endswith(".py")]
        checks = []
        if python_files:
            checks.append(CheckSpec(id="syntax", kind="syntax", targets=python_files))
        checks.append(CheckSpec(id="tests", kind="pytest", targets=[TEST_FILE]))
        results = []
        for check in checks:
            self.store.check_budget()
            print(f"check: {check.kind} revision={self.store.manifest.fixes}", flush=True)
            result = await self.executor(
                check,
                snapshot,
                suite,
                self.store.manifest.image_id,
                evidence_dir=self.store.root / "checks" / check_id / check.id,
                run_id=self.store.manifest.run_id,
            )
            results.append(result)
            if result.status != "passed":
                break
        return results

    def finish(self, error: str = "", *, cancelled: bool = False) -> Path | None:
        output = None
        try:
            if self.files:
                files = dict(self.files)
                if self.tests:
                    files[TEST_FILE] = self.tests
                snapshot = self.store.root / "exports" / uuid.uuid4().hex
                export_hash = materialize_snapshot(snapshot, files)
                destination = Path(self.store.manifest.output_repo)
                if destination.exists() and tree_hash(destination) != export_hash:
                    # Never overwrite a previous export or edits made by the user.
                    destination = snapshot
                materialize_snapshot(destination, files)
                output = destination
                self.store.manifest.export_path = str(output)
                self.store.manifest.export_hash = export_hash
        except (OSError, ValueError) as export_error:
            error = f"{error}\nExport failed: {export_error}".strip()
        complete = self.plan_value is not None and all(
            t.path in self.files for t in self.plan_value.files
        )
        outcome = (
            "complete"
            if output and complete and self.verified and not error
            else "draft"
            if output
            else "failed"
        )
        if cancelled:
            outcome = "cancelled"
        self.store.manifest.outcome = outcome
        self.store.save_manifest()
        coverage = next((r.coverage for r in reversed(self.results) if r.coverage), {})
        coverage_text = " / ".join(
            f"{coverage[name]:.2f}%" if coverage.get(name) is not None else "n/a"
            for name in ("line_percent", "branch_percent")
        )
        report = {
            "outcome": outcome,
            "export_path": str(output) if output else "",
            "generation_complete": complete,
            "tests_verified": self.verified,
            "warnings": self.warnings,
            "error": error,
            "calls_reserved": self.store.manifest.calls_reserved,
            "repairs": self.store.manifest.fixes,
            "measured_cost": None,
            "checks": [r.model_dump() for r in self.results],
            "coverage": coverage,
        }
        atomic_write(self.store.root / "report.json", json.dumps(report, indent=2))
        atomic_write(
            self.store.root / "report.md",
            f"# {outcome}\n\nRepository: {output}\n\nTests passed: {self.verified}\n\n"
            + f"Coverage (lines / branches): {coverage_text}\n\n"
            + "\n".join([error, *self.warnings]),
        )
        return output

    async def invoke(self, name: str, packet: dict):
        role = "planner" if name in {"plan", "author_tests"} else "worker"
        operation = getattr(self, name)
        current = packet
        for attempt in range(self.store.manifest.limits.schema_repairs + 1):
            async with self.slots:
                call_id = self.store.reserve_call(role, name)
                prefix = f"calls/{call_id}"
                rendered = await operation.render(self, current)
                self.store.save_artifact(f"{prefix}/prompt.txt", rendered)
                session = Session(provider=self.providers[role])
                print(f"{name}: attempt={attempt + 1} call={call_id}", flush=True)
                try:
                    result = await asyncio.wait_for(
                        operation(current, session=session), self.store.manifest.limits.call_timeout
                    )
                    if attempt:
                        result = TypeAdapter(OPERATIONS[name]).validate_json(result)
                        self.validate_output(name, result)
                    return result
                except (ValidationError, ValueError) as error:
                    if not session.history or attempt == self.store.manifest.limits.schema_repairs:
                        raise
                    current = {
                        "request": packet,
                        "invalid_response": session.history[-1]["text"],
                        "validation_errors": str(error),
                        "schema": TypeAdapter(OPERATIONS[name]).json_schema(),
                    }
                    operation = self.repair_json
                finally:
                    self.store.save_artifact(
                        f"{prefix}/history.json", json.dumps(session.history, indent=2)
                    )

    def validate_output(self, name, result):
        if name in {"plan", "repair"}:
            paths = set()
            for file in result.files:
                output_path(Path(self.store.manifest.output_repo), file.path)
                if file.path.startswith("tests/"):
                    raise ValueError(
                        "Production files must be outside tests/; tests are authored separately"
                    )
                if file.path in paths or any(
                    file.path.startswith(p + "/") or p.startswith(file.path + "/") for p in paths
                ):
                    raise ValueError(f"Duplicate or conflicting path: {file.path}")
                paths.add(file.path)

    @prompt(template="simple/plan.j2", output_type=Plan)
    async def plan(self, packet, *, generated) -> Plan:
        self.validate_output("plan", generated)
        return generated

    @prompt(template="simple/implement.j2")
    async def implement(self, packet, *, generated) -> str:
        return file_text(generated)

    @prompt(template="simple/author_tests.j2")
    async def author_tests(self, packet, *, generated) -> str:
        return file_text(generated)

    @prompt(template="simple/repair.j2", output_type=Revision)
    async def repair(self, packet, *, generated) -> Revision:
        self.validate_output("repair", generated)
        return generated

    @prompt(template="simple/repair_json.j2")
    async def repair_json(self, packet): ...


async def run_workflow(coder: PaperCoder, paper: str) -> Path | None:
    try:
        await asyncio.wait_for(
            coder.run(paper),
            max(0, coder.store.manifest.limits.run_timeout - coder.store.manifest.active_seconds),
        )
    except asyncio.CancelledError:
        coder.finish("Run cancelled", cancelled=True)
        raise
    except Exception as error:  # noqa: BLE001 - retain generated files and report at the run boundary
        return coder.finish(f"{type(error).__name__}: {error}")
    return coder.finish()
