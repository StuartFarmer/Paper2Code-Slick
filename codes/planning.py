"""Check cross-record references, task ownership and acceptance coverage."""

import ast
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from .contracts import Extraction, PaperSpec, Review, TaskPlan, TestSuite
from .paper import PaperIndex
from .paths import output_path


def unique(items, label: str) -> dict:
    result = {item.id: item for item in items}
    if len(result) != len(items):
        raise ValueError(f"Duplicate {label} IDs")
    return result


def validate_sources(extraction: Extraction, index: PaperIndex) -> None:
    excerpts = {e.source_id: e for e in index.excerpts}
    lines = index.text.splitlines(keepends=True)
    unique(extraction.requirements, "requirement")
    for requirement in extraction.requirements:
        if requirement.basis == "paper" and not requirement.sources:
            raise ValueError(f"Paper requirement has no sources: {requirement.id}")
        for ref in requirement.sources:
            excerpt = excerpts.get(ref.source_id)
            if excerpt is None or not (
                excerpt.start_line <= ref.start_line <= ref.end_line <= excerpt.end_line
            ):
                raise ValueError(f"Invalid source span: {ref.source_id}")
            if ref.quote not in "".join(lines[ref.start_line - 1 : ref.end_line]):
                raise ValueError(f"Quote not present in source span: {requirement.id}")


def ancestors(plan: TaskPlan) -> dict[str, set[str]]:
    tasks = unique(plan.tasks, "task")
    for task in tasks.values():
        if len(set(task.depends_on)) != len(task.depends_on) or set(task.depends_on) - tasks.keys():
            raise ValueError(f"Invalid dependencies for {task.id}")
    try:
        order = TopologicalSorter({t.id: t.depends_on for t in plan.tasks}).static_order()
        result = {}
        for name in order:
            result[name] = set(tasks[name].depends_on)
            for dep in tasks[name].depends_on:
                result[name].update(result[dep])
        return result
    except CycleError as error:
        raise ValueError("Task dependency cycle") from error


def validate_plan(spec: PaperSpec, plan: TaskPlan) -> None:
    requirements = unique(spec.requirements, "requirement")
    interfaces = unique(spec.interfaces, "interface")
    upstream = ancestors(plan)
    paths, producers, covered = {}, {}, set()
    for requirement in spec.requirements:
        if (
            requirement.claim_kind == "empirical"
            and requirement.verification_scope == "v1_required"
        ):
            raise ValueError(
                f"V1 synthetic checks cannot establish empirical results: {requirement.id}"
            )
        if requirement.basis == "paper" and not requirement.sources:
            raise ValueError(f"Missing paper evidence: {requirement.id}")
        if requirement.basis == "engineering_choice" and not requirement.rationale.strip():
            raise ValueError(f"Missing engineering rationale: {requirement.id}")
        if requirement.verification_scope == "deferred_empirical" and (
            requirement.claim_kind != "empirical" or not requirement.rationale.strip()
        ):
            raise ValueError(f"Invalid empirical deferral: {requirement.id}")
    for task in plan.tasks:
        output_path(Path("/task-ids"), task.id)
        if "/" in task.id:
            raise ValueError("Task IDs must not contain directories")
        if set(task.requirement_ids) - requirements.keys():
            raise ValueError(f"Unknown requirement in {task.id}")
        if any(requirements[r].basis == "unresolved" for r in task.requirement_ids):
            raise ValueError(f"Unresolved requirement in {task.id}")
        covered.update(task.requirement_ids)
        for name in task.owned_paths:
            output_path(Path("/production"), name)
            if name.split("/")[0] in {"tests", "codes", "docker", "calls", "tasks", "accepted"}:
                raise ValueError(f"Reserved production path: {name}")
            if name in paths or any(
                name.startswith(p + "/") or p.startswith(name + "/") for p in paths
            ):
                raise ValueError(f"Conflicting file ownership: {name}")
            paths[name] = task.id
        if set(task.produces + task.consumes) - interfaces.keys():
            raise ValueError(f"Unknown interface in {task.id}")
        for interface in task.produces:
            if interface in producers:
                raise ValueError(f"Multiple interface producers: {interface}")
            producers[interface] = task.id
    if interfaces.keys() - producers.keys():
        raise ValueError("Unowned interfaces")
    for task in plan.tasks:
        for interface in task.consumes:
            if producers[interface] not in upstream[task.id]:
                raise ValueError(f"Interface producer is not a dependency: {task.id}/{interface}")
    required = {r.id for r in spec.requirements if r.verification_scope == "v1_required"}
    if required - covered:
        raise ValueError(f"Uncovered requirements: {sorted(required - covered)}")


def validate_review(review: Review) -> None:
    unique(review.findings, "finding")
    if review.verdict == "pass" and (
        review.unresolved_requirement_ids or any(f.severity == "blocking" for f in review.findings)
    ):
        raise ValueError("Passing review has unresolved/blocking findings")
    if review.verdict != "pass" and not (review.findings or review.unresolved_requirement_ids):
        raise ValueError("Nonpassing review must explain its findings")


def validate_suite(spec: PaperSpec, plan: TaskPlan, suite: TestSuite) -> None:
    requirements = unique(spec.requirements, "requirement")
    unique(suite.properties, "property")
    files = {file.path: file.content for file in suite.files}
    if not suite.properties or len(files) != len(suite.files):
        raise ValueError("Empty properties or duplicate test paths")
    for name, content in files.items():
        output_path(Path("/suite"), name)
        if (
            not name.startswith("tests/acceptance/")
            or not name.endswith(".py")
            or Path(name).name == "conftest.py"
        ):
            raise ValueError(f"Forbidden acceptance file: {name}")
        try:
            tree = ast.parse(content, filename=name)
        except SyntaxError as error:
            raise ValueError(f"Invalid test syntax: {name}") from error
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in {"skip", "skipif", "xfail", "settings"}
            ) or (
                isinstance(node, ast.ImportFrom)
                and any(
                    alias.name in {"skip", "skipif", "xfail", "settings"} for alias in node.names
                )
            ):
                raise ValueError(f"Forbidden test skip/settings override: {name}")
    task_ids = {t.id for t in plan.tasks}
    if set(suite.task_targets) != task_ids or not suite.integration_targets:
        raise ValueError("Missing task/integration targets")
    nodes = set(suite.integration_targets)
    for targets in suite.task_targets.values():
        if not targets:
            raise ValueError("Empty task targets")
        nodes.update(targets)
    for node in nodes:
        path, separator, symbol = node.partition("::")
        if not separator or path not in files or not symbol or node.startswith("-"):
            raise ValueError(f"Unknown test node: {node}")
    covered = set()
    for prop in suite.properties:
        if set(prop.requirement_ids) - requirements.keys() or set(prop.node_ids) - nodes:
            raise ValueError(f"Dangling property evidence: {prop.id}")
        covered.update(prop.requirement_ids)
    required = {r.id for r in spec.requirements if r.verification_scope == "v1_required"}
    if required - covered:
        raise ValueError("Missing requirement/property coverage")
    for task in plan.tasks:
        task_coverage = {
            r
            for prop in suite.properties
            if set(prop.node_ids) & set(suite.task_targets[task.id])
            for r in prop.requirement_ids
        }
        if set(task.requirement_ids) & required - task_coverage:
            raise ValueError(f"Missing task property coverage: {task.id}")
