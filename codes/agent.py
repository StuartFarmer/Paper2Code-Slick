"""Typed Slick operations for the verified, short-context paper workflow."""

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from slick import Session, prompt, workflow

from .context import bounded_groups, build_packet, check_input_size, resolve_context
from .contracts import (
    Candidate,
    CheckSpec,
    Diagnosis,
    ExecutionResult,
    Extraction,
    PaperSpec,
    RequirementEvidence,
    Review,
    RunReport,
    TaskPlan,
    TaskRecord,
    TaskSpec,
    TestSuite,
    WorkerReply,
)
from .execution import (
    contract_scaffolds,
    materialize_snapshot,
    run_check,
    stage_candidate,
    tree_hash,
)
from .paper import PaperIndex
from .planning import ancestors, validate_plan, validate_review, validate_sources, validate_suite
from .store import BudgetExceeded, RunStore, atomic_write, digest

OPERATIONS = {
    "extract_requirements": Extraction,
    "reconcile_spec": PaperSpec,
    "plan_tasks": TaskPlan,
    "review_spec": Review,
    "author_tests": TestSuite,
    "review_tests": Review,
    "implement_task": WorkerReply,
    "review_task": Review,
    "diagnose": Diagnosis,
    "repair_task": WorkerReply,
    "review_fix": Review,
    "review_fidelity": Review,
}


class PaperCoder:
    def __init__(
        self, store: RunStore, provider, *, planner=None, reviewer=None, executor=run_check
    ):
        self.store = store
        self.providers = {
            "worker": provider,
            "planner": planner or provider,
            "reviewer": reviewer or provider,
        }
        self.model_slots = asyncio.Semaphore(store.manifest.limits.concurrency)
        self.test_slots = asyncio.Semaphore(store.manifest.limits.test_concurrency)
        self.executor = executor

    @workflow
    async def run(self, index: PaperIndex) -> Path | None:
        self.snapshot_source(index)
        spec, plan = await self.prepare_plan(index)
        suite = await self.prepare_acceptance(spec, plan, index)
        self.configure_run(index, spec, plan, suite)
        await self.execute_plan()
        return await self.finish()

    def snapshot_source(self, index: PaperIndex) -> None:
        self.integration_verified = False
        source = index.original.decode("utf-8")
        if "source/original.txt" in self.store.artifacts:
            if self.store.read_artifact("source/original.txt") != source:
                raise ValueError("Source changed; create a new run")
        else:
            self.store.save_artifact("source/original.txt", source)
        if "source/index.json" not in self.store.artifacts:
            self.store.save_artifact(
                "source/index.json",
                json.dumps(
                    {
                        "format": index.format,
                        "text": index.text,
                        "locations": index.locations,
                        "excerpts": [asdict(e) for e in index.excerpts],
                        "labels": index.labels,
                        "unresolved_references": index.unresolved_references,
                    },
                    indent=2,
                ),
            )

    async def finish(self) -> Path | None:
        if not all(r.state == "accepted" for r in self.records.values()):
            self.write_report("incomplete", "One or more tasks are blocked")
            return None
        output = await self.integrate_and_export()
        self.write_report("complete")
        return output

    async def integrate_and_export(self) -> Path:
        files = {}
        for task in self.plan.tasks:
            if not self.accepted(task):
                raise ValueError(f"Task has missing or stale acceptance evidence: {task.id}")
            candidate = Candidate.model_validate_json(
                self.store.read_artifact(self.records[task.id].candidate_artifact)
            )
            files.update({f.path: f.content for f in candidate.files})
        integrated_hash = digest(json.dumps(files, sort_keys=True).encode())
        integrated = self.store.root / "snapshots" / f"integrated-{integrated_hash}"
        materialize_snapshot(integrated, files)
        nodes = list(
            dict.fromkeys(
                [n for group in self.suite.task_targets.values() for n in group]
                + self.suite.integration_targets
            )
        )
        checks = [
            CheckSpec(id="integration", kind="pytest", targets=nodes),
            CheckSpec(
                id="smoke",
                kind="smoke",
                targets=self.suite.integration_targets,
                timeout_seconds=300,
            ),
        ]
        for check in checks:
            result = await self.check(
                check, integrated, self.suite_root, f"integration/{integrated_hash}/{check.id}"
            )
            if result.status != "passed" or not result.collected_tests:
                if await self.repair_integration(result, integrated_hash):
                    await self.execute_plan()
                    return await self.integrate_and_export()
                raise ValueError(
                    f"Final {check.id} failed: {result.status}; see integration evidence"
                )
        self.integration_verified = True
        for number, group in enumerate(
            bounded_groups([r.model_dump() for r in self.spec.requirements])
        ):
            ids = {r["id"] for r in group}
            source_ids = {s["source_id"] for r in group for s in r["sources"]}
            review = await self.cached(
                "review_fidelity",
                {
                    "requirements": group,
                    "sources": [
                        asdict(e) for e in self.index.excerpts if e.source_id in source_ids
                    ],
                    "properties": [
                        p.model_dump()
                        for p in self.suite.properties
                        if set(p.requirement_ids) & ids
                    ],
                    "task_evidence": [
                        self.records[t.id].model_dump()
                        for t in self.plan.tasks
                        if set(t.requirement_ids) & ids
                    ],
                    "deviations": self.spec.deviations,
                    "unresolved_inputs": self.index.unresolved_references,
                },
                f"integration/{integrated_hash}/fidelity-{number}.json",
                validator=validate_review,
            )
            if review.verdict != "pass":
                raise ValueError(
                    f"Final fidelity review blocked group {number}: {review.model_dump_json()}"
                )
        files.update({f.path: f.content for f in self.suite.files})
        accepted_root = self.store.root / "accepted"
        accepted_hash = materialize_snapshot(accepted_root, files)
        destination = Path(self.store.manifest.output_repo)
        if destination.exists():
            if (
                self.store.manifest.accepted_hash != accepted_hash
                or tree_hash(destination) != accepted_hash
            ):
                raise FileExistsError(f"Export path already exists: {destination}")
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".paper2code-export-", dir=destination.parent))
        try:
            shutil.copytree(accepted_root, temporary, dirs_exist_ok=True)
            self.store.manifest.accepted_hash = accepted_hash
            self.store.save_manifest()
            if destination.exists():
                raise FileExistsError(f"Export path already exists: {destination}")
            os.rename(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return destination

    async def repair_integration(self, result: ExecutionResult, snapshot_id: str) -> bool:
        if result.status != "failed" or not result.failed_nodes:
            return False
        failed_properties = [
            p
            for p in self.suite.properties
            if any(
                node == target or node.startswith(target + "[")
                for node in result.failed_nodes
                for target in p.node_ids
            )
        ]
        requirement_ids = {r for prop in failed_properties for r in prop.requirement_ids}
        affected = [task for task in self.plan.tasks if set(task.requirement_ids) & requirement_ids]
        if not affected:
            return False
        decisions = []
        for task in affected:
            record = self.records[task.id]
            if record.fixes >= self.store.manifest.limits.code_fixes:
                record.state, record.blocker = "blocked", "Integration repair budget exhausted"
                self.store.save_task(record)
                return False
            _, dependencies = self.dependencies(task)
            candidate = Candidate.model_validate_json(
                self.store.read_artifact(record.candidate_artifact)
            )
            packet = build_packet(task, self.spec, self.index, dependencies, self.suite)
            packet.update(
                candidate_files=[f.model_dump() for f in candidate.files],
                checks=[self.evidence(result)],
                evidence_artifact_ids=[f"integration/{snapshot_id}/{result.check_id}/result.json"],
            )
            diagnosis = await self.invoke("diagnose", packet, task_id=task.id)
            if diagnosis.category != "implementation" or set(diagnosis.affected_paths) - set(
                task.owned_paths
            ):
                record.state, record.blocker = (
                    "blocked",
                    "Integration correction requires specification/test review",
                )
                self.store.save_task(record)
                return False
            artifact = self.store.save_artifact(
                f"integration/{snapshot_id}/repair-{task.id}-{record.fixes}.json",
                diagnosis.model_dump_json(indent=2),
            )
            decisions.append((record, artifact))
        for record, artifact in decisions:
            record.fixes += 1
            record.diagnosis_artifact = artifact
            record.state, record.blocker = "pending", "Integration regression"
            self.store.save_task(record)
        return True

    def write_report(self, outcome: str, error: str = "") -> None:
        records = getattr(self, "records", {})
        spec, suite = getattr(self, "spec", None), getattr(self, "suite", None)
        evidence = {}
        if spec and suite:
            for requirement in spec.requirements:
                properties = [p for p in suite.properties if requirement.id in p.requirement_ids]
                tasks = [t for t in self.plan.tasks if requirement.id in t.requirement_ids]
                owners = [self.records[t.id] for t in tasks]
                status = "unresolved"
                if requirement.verification_scope == "deferred_empirical":
                    status = "deferred_empirical"
                elif tasks and all(self.accepted(t) for t in tasks):
                    status = (
                        "tested_engineering_choice"
                        if requirement.basis == "engineering_choice"
                        else "tested_domain"
                        if requirement.claim_kind == "mathematical"
                        else "tested_method"
                    )
                evidence[requirement.id] = RequirementEvidence(
                    status=status,
                    sources=requirement.sources,
                    property_ids=[p.id for p in properties],
                    node_ids=list(dict.fromkeys(n for p in properties for n in p.node_ids)),
                    execution_artifacts=[a for record in owners for a in record.check_artifacts],
                    rationale=requirement.rationale,
                )
        complete = bool(records) and all(self.accepted(t) for t in self.plan.tasks)
        self.store._charge_elapsed()
        report = RunReport(
            outcome=outcome,
            generation_complete=complete,
            tests_verified=complete,
            integration_verified=getattr(self, "integration_verified", False),
            requirements=evidence,
            deviations=spec.deviations if spec else [],
            properties={p.id: p for p in suite.properties} if suite else {},
            calibration={p.id: "uncalibrated" for p in suite.properties} if suite else {},
            blocked_tasks={name: r.blocker for name, r in records.items() if r.state != "accepted"},
            calls_reserved=self.store.manifest.calls_reserved,
            active_seconds=self.store.manifest.active_seconds,
            measured_cost=None,
            input_hashes=self.store.manifest.input_hashes,
            image_id=self.store.manifest.image_id,
            models=self.store.manifest.models,
            error=error,
        )
        self.store.save_artifact(
            f"reports/{uuid.uuid4().hex}.json", report.model_dump_json(indent=2)
        )
        atomic_write(self.store.root / "report.json", report.model_dump_json(indent=2) + "\n")
        atomic_write(
            self.store.root / "report.md",
            f"# Paper2Code run: {outcome}\n\nCalls: {report.calls_reserved}\n\nTests verified: {report.tests_verified}\n\nIntegration verified: {report.integration_verified}\n\n{error}\n\nPassing synthetic tests does not establish published-result reproduction. See report.json for claim-level evidence.\n",
        )
        self.store.manifest.outcome = outcome
        self.store.save_manifest()

    def configure_run(
        self, index: PaperIndex, spec: PaperSpec, plan: TaskPlan, suite: TestSuite
    ) -> None:
        validate_plan(spec, plan)
        validate_suite(spec, plan, suite)
        self.index, self.spec, self.plan, self.suite = index, spec, plan, suite
        self.upstream = ancestors(plan)
        self.plan_hash = digest(plan.model_dump_json().encode())
        self.suite_root = self.store.root / "snapshots" / "acceptance"
        self.suite_hash = materialize_snapshot(
            self.suite_root, {f.path: f.content for f in suite.files}
        )
        self.records = {}
        for task in plan.tasks:
            if (self.store.root / "tasks" / task.id / "state.json").exists():
                record = self.store.load_task(task.id)
                if record.plan_hash != self.plan_hash:
                    raise ValueError("Task plan changed; create a new run")
            else:
                record = TaskRecord(task_id=task.id, plan_hash=self.plan_hash, state="pending")
                self.store.save_task(record)
            self.records[task.id] = record

    async def execute_plan(self) -> None:
        by_id = {task.id: task for task in self.plan.tasks}
        for task_id in self.upstream:
            task = by_id[task_id]
            record = self.records[task.id]
            if record.state == "accepted" and not self.accepted(task):
                record.state = "pending"
                record.blocker = "Accepted evidence invalidated"
                self.store.save_task(record)
        while True:
            for task in self.plan.tasks:
                record = self.records[task.id]
                if record.state not in {"accepted", "blocked"} and any(
                    self.records[d].state == "blocked" for d in self.upstream[task.id]
                ):
                    record.state, record.blocker = "blocked", "Required dependency is blocked"
                    self.store.save_task(record)
            ready = [
                task
                for task in self.plan.tasks
                if self.records[task.id].state not in {"accepted", "blocked"}
                and all(self.records[d].state == "accepted" for d in task.depends_on)
            ]
            if not ready:
                return
            pending = [asyncio.create_task(self.execute_task(task)) for task in ready]
            try:
                await asyncio.gather(*pending)
            except BaseException:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise

    def dependencies(self, task: TaskSpec) -> tuple[dict[str, str], dict[str, str]]:
        versions, files = {}, {}
        for task_id in sorted(self.upstream[task.id]):
            record = self.records[task_id]
            if record.state != "accepted":
                raise ValueError(f"Dependency not accepted: {task_id}")
            versions[task_id] = record.candidate_hash
            candidate = Candidate.model_validate_json(
                self.store.read_artifact(record.candidate_artifact)
            )
            files.update({f.path: f.content for f in candidate.files})
        return versions, files

    def accepted(self, task: TaskSpec) -> bool:
        record = self.records[task.id]
        if record.state != "accepted":
            return False
        if any(self.records[d].state != "accepted" for d in self.upstream[task.id]):
            return False
        versions, _ = self.dependencies(task)
        if (
            record.dependencies != versions
            or record.suite_hash != self.suite_hash
            or record.image_id != self.store.manifest.image_id
        ):
            return False
        if len(record.check_artifacts) != 3 or not record.review_artifacts:
            return False
        results = [
            ExecutionResult.model_validate_json(self.store.read_artifact(a))
            for a in record.check_artifacts
        ]
        expected = (
            record.candidate_hash,
            self.suite_hash,
            record.image_id,
            digest(json.dumps(versions, sort_keys=True).encode()),
        )
        if {r.check_id for r in results} != {"syntax", "imports", "pytest"}:
            return False
        for result in results:
            if (
                result.status != "passed"
                or (
                    result.candidate_hash,
                    result.suite_hash,
                    result.image_id,
                    result.dependency_hash,
                )
                != expected
            ):
                return False
            if result.check_id == "pytest" and not result.collected_tests:
                return False
        review = Review.model_validate_json(self.store.read_artifact(record.review_artifacts[-1]))
        validate_review(review)
        return review.verdict == "pass"

    async def execute_task(self, task: TaskSpec) -> TaskRecord:
        record = self.records[task.id]
        if self.accepted(task):
            return record
        try:
            versions, dependencies = self.dependencies(task)
            dependency_hash = digest(json.dumps(versions, sort_keys=True).encode())
            packet = build_packet(task, self.spec, self.index, dependencies, self.suite)
            operation = "implement_task"
            if record.diagnosis_artifact and record.candidate_artifact:
                previous = Candidate.model_validate_json(
                    self.store.read_artifact(record.candidate_artifact)
                )
                packet.update(
                    candidate_files=[f.model_dump() for f in previous.files],
                    diagnosis=json.loads(self.store.read_artifact(record.diagnosis_artifact)),
                )
                operation = "repair_task"
            while True:
                record.state = "implementing"
                record.generations += 1
                self.store.save_task(record)
                reply = await self.invoke(operation, packet, task_id=task.id)
                if reply.kind == "blocked":
                    record.blocker = reply.reason
                    break
                if reply.kind == "needs_context":
                    if record.context_requests >= self.store.manifest.limits.context_requests:
                        record.blocker = "Context expansion budget exhausted"
                        break
                    record.context_requests += 1
                    self.store.save_task(record)
                    packet = resolve_context(reply, packet, self.index, self.spec, dependencies)
                    continue
                prefix = f"tasks/{task.id}/attempts/{record.generations}"
                candidate_artifact = self.store.save_artifact(
                    f"{prefix}/candidate.json", reply.model_dump_json(indent=2)
                )
                workspace = self.store.root / "snapshots" / task.id / str(record.generations)
                candidate_hash = stage_candidate(task, reply, workspace, dependencies=dependencies)
                record.candidate_hash, record.candidate_artifact = (
                    candidate_hash,
                    candidate_artifact,
                )
                record.state = "checking"
                self.store.save_task(record)
                python_files = [p for p in task.owned_paths if p.endswith(".py")]
                modules = [
                    p.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
                    for p in python_files
                ]
                checks = [
                    CheckSpec(id="syntax", kind="syntax", targets=python_files),
                    CheckSpec(id="imports", kind="imports", targets=modules),
                    CheckSpec(id="pytest", kind="pytest", targets=self.suite.task_targets[task.id]),
                ]
                results, artifacts = [], []
                for check in checks:
                    key = f"{prefix}/{check.id}"
                    result = await self.check(
                        check, workspace, self.suite_root, key, dependency_hash=dependency_hash
                    )
                    results.append(result)
                    artifacts.append(f"{key}/result.json")
                    record.check_artifacts = artifacts
                    self.store.save_task(record)
                    if result.status != "passed":
                        break
                if any(r.status == "infrastructure_error" for r in results):
                    record.blocker = (
                        "Execution infrastructure/test setup failure; see check artifacts"
                    )
                    record.check_artifacts = artifacts
                    break
                record.state = "reviewing"
                self.store.save_task(record)
                review_packet = {
                    **packet,
                    "candidate_files": [f.model_dump() for f in reply.files],
                    "checks": [self.evidence(r) for r in results],
                    "evidence_artifact_ids": artifacts,
                }
                review_name = "review_fix" if record.fixes else "review_task"
                review = await self.invoke(
                    review_name, review_packet, task_id=task.id, validator=validate_review
                )
                review_artifact = self.store.save_artifact(
                    f"{prefix}/review.json", review.model_dump_json(indent=2)
                )
                passed = (
                    len(results) == 3
                    and all(r.status == "passed" for r in results)
                    and bool(results[-1].collected_tests)
                )
                if passed and review.verdict == "pass":
                    current_versions, _ = self.dependencies(task)
                    if current_versions != versions:
                        raise ValueError("Dependencies changed before acceptance")
                    record.dependencies = versions
                    record.candidate_hash, record.candidate_artifact = (
                        candidate_hash,
                        candidate_artifact,
                    )
                    record.suite_hash, record.image_id = (
                        self.suite_hash,
                        self.store.manifest.image_id,
                    )
                    record.check_artifacts, record.review_artifacts = artifacts, [review_artifact]
                    record.state, record.blocker = "accepted", ""
                    record.diagnosis_artifact = ""
                    self.store.save_task(record)
                    return record
                if record.fixes >= self.store.manifest.limits.code_fixes:
                    record.blocker = "Code repair budget exhausted"
                    break
                diagnosis = await self.invoke(
                    "diagnose", {**review_packet, "review": review.model_dump()}, task_id=task.id
                )
                record.diagnosis_artifact = self.store.save_artifact(
                    f"{prefix}/diagnosis.json", diagnosis.model_dump_json(indent=2)
                )
                if diagnosis.category != "implementation" or set(diagnosis.affected_paths) - set(
                    task.owned_paths
                ):
                    record.blocker = (
                        f"Correction requires {diagnosis.category} review: {diagnosis.hypothesis}"
                    )
                    break
                record.fixes += 1
                record.state = "repairing"
                self.store.save_task(record)
                packet = {
                    **packet,
                    "candidate_files": [f.model_dump() for f in reply.files],
                    "diagnosis": diagnosis.model_dump(),
                    "prior_findings": [f.model_dump() for f in review.findings],
                    "checks": [self.evidence(r) for r in results],
                }
                operation = "repair_task"
        except ValueError as error:
            record.blocker = str(error)
        except asyncio.CancelledError:
            record.state = "cancelled"
            self.store.save_task(record)
            raise
        record.state = "blocked"
        self.store.save_task(record)
        return record

    async def check(
        self, check: CheckSpec, workspace: Path, suite: Path, key: str, *, dependency_hash: str = ""
    ) -> ExecutionResult:
        expected = (
            tree_hash(workspace),
            tree_hash(suite),
            self.store.manifest.image_id,
            dependency_hash,
        )
        artifact = f"{key}/result.json"
        if artifact in self.store.artifacts:
            result = ExecutionResult.model_validate_json(self.store.read_artifact(artifact))
        else:
            async with self.test_slots:
                self.store.check_budget()
                remaining = (
                    self.store.manifest.limits.run_timeout - self.store.manifest.active_seconds
                )
                check = check.model_copy(
                    update={"timeout_seconds": min(check.timeout_seconds, remaining)}
                )
                if f"{key}/request.json" not in self.store.artifacts:
                    self.store.save_artifact(f"{key}/request.json", check.model_dump_json())
                execution_id = uuid.uuid4().hex
                result = await self.executor(
                    check,
                    workspace,
                    suite,
                    self.store.manifest.image_id,
                    evidence_dir=self.store.root / "executor" / execution_id,
                    dependency_hash=dependency_hash,
                    run_id=self.store.manifest.run_id,
                )
                for stream in ("stdout", "stderr"):
                    path = Path(getattr(result, stream + "_artifact"))
                    artifact_path = self.store.save_artifact(
                        f"{key}/{execution_id}/{stream}.txt", path.read_text(errors="replace")
                    )
                    setattr(result, stream + "_artifact", artifact_path)
                self.store.save_artifact(artifact, result.model_dump_json(indent=2))
        if (
            result.candidate_hash,
            result.suite_hash,
            result.image_id,
            result.dependency_hash,
        ) != expected or result.check_id != check.id:
            raise ValueError("Execution evidence does not match current inputs")
        return result

    def evidence(self, result: ExecutionResult) -> dict:
        output = self.store.read_artifact(result.stdout_artifact) + self.store.read_artifact(
            result.stderr_artifact
        )
        return {
            "result": result.model_dump(),
            "output_tail": output.encode()[-8192:].decode(errors="replace"),
        }

    async def cached(self, name: str, packet: dict, artifact: str, *, validator=None):
        if artifact in self.store.artifacts:
            result = TypeAdapter(OPERATIONS[name]).validate_json(self.store.read_artifact(artifact))
            if validator:
                validator(result)
            return result
        result = await self.invoke(name, packet, task_id=artifact, validator=validator)
        self.store.save_artifact(artifact, result.model_dump_json(indent=2))
        return result

    async def prepare_acceptance(
        self, spec: PaperSpec, plan: TaskPlan, index: PaperIndex
    ) -> TestSuite:
        if "suite.json" in self.store.artifacts:
            suite = TestSuite.model_validate_json(self.store.read_artifact("suite.json"))
            validate_suite(spec, plan, suite)
            return suite
        groups = [(task.id, [task], False) for task in plan.tasks]
        edges = [(task, dependency) for task in plan.tasks for dependency in task.depends_on]
        by_id = {task.id: task for task in plan.tasks}
        if edges:
            groups += [(f"edge-{task.id}-{dep}", [by_id[dep], task], True) for task, dep in edges]
        else:
            groups.append(("integration", plan.tasks, True))
        files, properties, targets, integration_targets = [], [], {}, []
        scaffold = self.store.root / "snapshots" / "scaffold"
        materialize_snapshot(scaffold, contract_scaffolds(spec, plan))
        for group_id, tasks, integration in groups:
            required_ids = {r for task in tasks for r in task.requirement_ids}
            requirements = [r for r in spec.requirements if r.id in required_ids]
            source_ids = {ref.source_id for r in requirements for ref in r.sources}
            interface_ids = {i for task in tasks for i in task.consumes + task.produces}
            packet = {
                "tasks": [t.model_dump() for t in tasks],
                "requirements": [r.model_dump() for r in requirements],
                "interfaces": [i.model_dump() for i in spec.interfaces if i.id in interface_ids],
                "sources": [asdict(e) for e in index.excerpts if e.source_id in source_ids],
                "prefix": f"tests/acceptance/{group_id}/",
                "property_id_prefix": group_id,
                "fragment_kind": "integration" if integration else "task",
                "integration_criteria": plan.integration_criteria if integration else [],
            }

            def validate_fragment(
                fragment,
                packet=packet,
                integration=integration,
                group_id=group_id,
                required_ids=required_ids,
            ):
                if any(not f.path.startswith(packet["prefix"]) for f in fragment.files):
                    raise ValueError("Acceptance fragment escaped its owned prefix")
                if set(fragment.task_targets) != (set() if integration else {group_id}):
                    raise ValueError("Incorrect fragment task targets")
                if bool(fragment.integration_targets) != integration:
                    raise ValueError("Incorrect fragment integration targets")
                if any(set(p.requirement_ids) - required_ids for p in fragment.properties):
                    raise ValueError("Property references an unrelated requirement")

            fragment = await self.cached(
                "author_tests",
                packet,
                f"planning/tests-{group_id}.json",
                validator=validate_fragment,
            )
            fragment_root = self.store.root / "snapshots" / f"tests-{group_id}"
            materialize_snapshot(fragment_root, {f.path: f.content for f in fragment.files})
            node_targets = fragment.integration_targets or fragment.task_targets[group_id]
            baseline = await self.check(
                CheckSpec(id=f"baseline-{group_id}", kind="pytest", targets=node_targets),
                scaffold,
                fragment_root,
                f"baseline/{group_id}",
            )
            if baseline.status not in {"passed", "failed"}:
                raise ValueError(f"Test scaffolding/setup failed for {group_id}: {baseline.status}")
            review = await self.cached(
                "review_tests",
                {
                    **packet,
                    "suite": fragment.model_dump(),
                    "scaffold_execution": self.evidence(baseline),
                },
                f"planning/test-review-{group_id}.json",
                validator=validate_review,
            )
            if review.verdict != "pass":
                raise ValueError(
                    f"Acceptance review blocked {group_id}: {review.model_dump_json()}"
                )
            if baseline.status == "passed" or not baseline.collected_tests:
                raise ValueError(
                    f"Acceptance fragment does not reject the unimplemented scaffold: {group_id}"
                )
            files.extend(fragment.files)
            properties.extend(fragment.properties)
            targets.update(fragment.task_targets)
            integration_targets.extend(fragment.integration_targets)
        suite = TestSuite(
            files=files,
            properties=properties,
            task_targets=targets,
            integration_targets=integration_targets,
        )
        validate_suite(spec, plan, suite)
        self.store.save_artifact("suite.json", suite.model_dump_json(indent=2))
        self.store.manifest.suite_hash = digest(suite.model_dump_json().encode())
        self.store.save_manifest()
        return suite

    async def prepare_plan(self, index: PaperIndex) -> tuple[PaperSpec, TaskPlan]:
        if "plan.json" in self.store.artifacts:
            spec = PaperSpec.model_validate_json(self.store.read_artifact("spec.json"))
            plan = TaskPlan.model_validate_json(self.store.read_artifact("plan.json"))
            validate_plan(spec, plan)
            return spec, plan
        calls = [
            self.cached(
                "extract_requirements",
                {"excerpt": asdict(e), "id_prefix": e.source_id},
                f"planning/extract-{e.source_id}.json",
                validator=lambda x: validate_sources(x, index),
            )
            for e in index.excerpts
        ]
        pending = [asyncio.create_task(call) for call in calls]
        try:
            extractions = await asyncio.gather(*pending)
        except BaseException:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        requirements, interfaces, invariants, deviations, tasks, criteria = {}, {}, [], [], [], []
        extracted = [r.model_dump() for result in extractions for r in result.requirements]
        for number, group in enumerate(bounded_groups(extracted)):
            source_ids = {s["source_id"] for r in group for s in r["sources"]}
            packet = {
                "requirements": group,
                "id_prefix": f"g{number}",
                "sources": [asdict(e) for e in index.excerpts if e.source_id in source_ids],
                "interface_registry": [i.model_dump() for i in interfaces.values()],
            }

            def validate_fragment(fragment, group=group):
                if {r.id for r in fragment.requirements} != {r["id"] for r in group}:
                    raise ValueError("Specification fragment changed its allocated requirement IDs")
                validate_sources(
                    Extraction(requirements=fragment.requirements, unresolved_references=[]), index
                )
                for interface in fragment.interfaces:
                    if interface.id in interfaces and interfaces[interface.id] != interface:
                        raise ValueError(f"Conflicting interface definition: {interface.id}")

            fragment = await self.cached(
                "reconcile_spec",
                packet,
                f"planning/spec-{number}.json",
                validator=validate_fragment,
            )
            review = await self.cached(
                "review_spec",
                {**packet, "spec": fragment.model_dump()},
                f"planning/spec-review-{number}.json",
                validator=validate_review,
            )
            if review.verdict != "pass":
                raise ValueError(
                    f"Specification review blocked group {number}: {review.model_dump_json()}"
                )
            if requirements.keys() & {r.id for r in fragment.requirements}:
                raise ValueError("Duplicate requirement IDs across extraction groups")
            requirements.update({r.id: r for r in fragment.requirements})
            interfaces.update({i.id: i for i in fragment.interfaces})
            invariants.extend(fragment.global_invariants)
            deviations.extend(fragment.deviations)
            plan_fragment = await self.cached(
                "plan_tasks",
                {
                    "spec": fragment.model_dump(),
                    "id_prefix": f"g{number}",
                    "existing_owners": [
                        {"id": t.id, "produces": t.produces, "owned_paths": t.owned_paths}
                        for t in tasks
                    ],
                },
                f"planning/tasks-{number}.json",
            )
            if any(
                set(t.requirement_ids) - {r.id for r in fragment.requirements}
                for t in plan_fragment.tasks
            ):
                raise ValueError("Task fragment escaped allocated requirements")
            tasks.extend(plan_fragment.tasks)
            criteria.extend(plan_fragment.integration_criteria)
        spec = PaperSpec(
            requirements=list(requirements.values()),
            interfaces=list(interfaces.values()),
            global_invariants=list(dict.fromkeys(invariants)),
            deviations=list(dict.fromkeys(deviations)),
        )
        plan = TaskPlan(tasks=tasks, integration_criteria=list(dict.fromkeys(criteria)))
        validate_plan(spec, plan)
        self.store.save_artifact("spec.json", spec.model_dump_json(indent=2))
        self.store.save_artifact("plan.json", plan.model_dump_json(indent=2))
        self.store.manifest.plan_hash = digest(plan.model_dump_json().encode())
        self.store.save_manifest()
        return spec, plan

    @prompt(template="improved/extract_requirements.j2", output_type=Extraction, max_turns=1)
    async def extract_requirements(self, packet: dict) -> Extraction:
        """Extract requirements with exact evidence from one excerpt."""

    @prompt(template="improved/reconcile_spec.j2", output_type=PaperSpec, max_turns=1)
    async def reconcile_spec(self, packet: dict) -> PaperSpec:
        """Resolve a bounded requirement group and its interfaces."""

    @prompt(template="improved/plan_tasks.j2", output_type=TaskPlan, max_turns=1)
    async def plan_tasks(self, packet: dict) -> TaskPlan:
        """Decompose a bounded specification fragment into owned tasks."""

    @prompt(template="improved/review_spec.j2", output_type=Review, max_turns=1)
    async def review_spec(self, packet: dict) -> Review:
        """Check source entailment and explicit assumptions."""

    @prompt(template="improved/author_tests.j2", output_type=TestSuite, max_turns=1)
    async def author_tests(self, packet: dict) -> TestSuite:
        """Author independent properties and numerical acceptance examples."""

    @prompt(template="improved/review_tests.j2", output_type=Review, max_turns=1)
    async def review_tests(self, packet: dict) -> Review:
        """Check scientific justification and executable test quality."""

    @prompt(template="improved/implement_task.j2", output_type=WorkerReply, max_turns=1)
    async def implement_task(self, packet: dict) -> WorkerReply:
        """Implement exactly the owned files or request identified context."""

    @prompt(template="improved/review_task.j2", output_type=Review, max_turns=1)
    async def review_task(self, packet: dict) -> Review:
        """Review candidate behavior against measured checks and requirements."""

    @prompt(template="improved/diagnose.j2", output_type=Diagnosis, max_turns=1)
    async def diagnose(self, packet: dict) -> Diagnosis:
        """Explain one evidenced failure before proposing a local repair."""

    @prompt(template="improved/repair_task.j2", output_type=WorkerReply, max_turns=1)
    async def repair_task(self, packet: dict) -> WorkerReply:
        """Repair owned production code without weakening acceptance tests."""

    @prompt(template="improved/review_fix.j2", output_type=Review, max_turns=1)
    async def review_fix(self, packet: dict) -> Review:
        """Verify the fix and previous findings on current evidence."""

    @prompt(template="improved/review_fidelity.j2", output_type=Review, max_turns=1)
    async def review_fidelity(self, packet: dict) -> Review:
        """Assess supported method claims and deferred empirical claims."""

    @prompt(template="improved/repair_schema.j2", max_turns=1)
    async def repair_schema(self, packet: dict) -> str:
        """Correct a rejected structured response with precise validation feedback."""

    async def invoke(self, name: str, packet: dict, *, task_id: str = "paper", validator=None):
        role = (
            "reviewer"
            if name.startswith("review_")
            else "planner"
            if name in {"extract_requirements", "reconcile_spec", "plan_tasks", "author_tests"}
            else "worker"
        )
        operation = getattr(self, name)
        current_packet = packet
        adapter = TypeAdapter(OPERATIONS[name])
        for attempt in range(self.store.manifest.limits.schema_repairs + 1):
            rendered = await operation.render(self, current_packet)
            check_input_size(rendered, self.store.manifest.limits.input_bytes)
            async with self.model_slots:
                call_id = self.store.reserve_call(role, task_id)
                prefix = f"calls/{call_id}"
                self.store.save_artifact(f"{prefix}/prompt.txt", rendered)
                session = Session(provider=self.providers[role])
                print(f"{name}: {task_id} attempt={attempt + 1} call={call_id}", flush=True)
                started = time.time()
                status = "failed"
                try:
                    remaining = (
                        self.store.manifest.limits.run_timeout - self.store.manifest.active_seconds
                    )
                    generated = await asyncio.wait_for(
                        operation(current_packet, session=session),
                        min(remaining, self.store.manifest.limits.call_timeout),
                    )
                    result = adapter.validate_json(generated) if attempt else generated
                    if validator is not None:
                        validator(result)
                    status = "completed"
                    return result
                except (ValidationError, ValueError) as error:
                    if not session.history:
                        raise
                    if attempt == self.store.manifest.limits.schema_repairs:
                        raise
                    if task_id in getattr(self, "records", {}):
                        self.records[task_id].schema_repairs += 1
                        self.store.save_task(self.records[task_id])
                    feedback = (
                        error.json(include_input=False, include_url=False)
                        if isinstance(error, ValidationError)
                        else str(error)
                    )
                    raw = session.history[-1]["text"] if session.history else ""
                    current_packet = {
                        "original": packet,
                        "invalid_response": raw,
                        "validation_errors": feedback,
                        "output_schema": adapter.json_schema(),
                    }
                    operation = self.repair_schema
                except asyncio.CancelledError:
                    status = "cancelled"
                    raise
                finally:
                    self.store.save_artifact(
                        f"{prefix}/history.json", json.dumps(session.history, indent=2)
                    )
                    self.store.save_artifact(
                        f"{prefix}/outcome.json",
                        json.dumps(
                            {
                                "status": status,
                                "operation": name,
                                "task_id": task_id,
                                "attempt": attempt,
                                "input_bytes": len(rendered.encode()),
                                "started": started,
                                "finished": time.time(),
                                "measured_tokens": None,
                                "measured_cost": None,
                            }
                        ),
                    )
                    self.store.check_budget()


async def run_verified(coder: PaperCoder, index: PaperIndex) -> Path | None:
    """Persist outcomes around Slick's restricted workflow syntax."""
    try:
        return await coder.run(index)
    except BudgetExceeded as error:
        coder.write_report("incomplete", str(error))
        return None
    except asyncio.CancelledError:
        coder.write_report("cancelled", "Run cancelled")
        raise
    except Exception as error:
        coder.write_report("failed", f"{type(error).__name__}: {error}")
        raise
