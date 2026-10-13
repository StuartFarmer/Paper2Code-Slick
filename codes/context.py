"""Build bounded, task-local packets without copying the full running history."""

import json
from dataclasses import asdict

from .contracts import ContextRequest, PaperSpec, TaskSpec, TestSuite
from .paper import PaperIndex


def check_input_size(text: str, limit: int = 32768) -> None:
    if len(text.encode("utf-8")) > limit:
        raise ValueError(f"Rendered input exceeds {limit} UTF-8 bytes; split the task or evidence")


def bounded_groups(records: list[dict], limit: int = 8192):
    group = []
    for record in records:
        check_input_size(json.dumps([record], ensure_ascii=False), limit)
        if group and len(json.dumps([*group, record], ensure_ascii=False).encode()) > limit:
            yield group
            group = []
        group.append(record)
    if group:
        yield group


def build_packet(
    task: TaskSpec,
    spec: PaperSpec,
    index: PaperIndex,
    dependencies: dict[str, str],
    suite: TestSuite,
    *,
    findings: list | None = None,
) -> dict:
    requirements = [r for r in spec.requirements if r.id in task.requirement_ids]
    source_ids = {s.source_id for r in requirements for s in r.sources}
    nodes = set(suite.task_targets[task.id])
    files = {node.split("::")[0] for node in nodes}
    modules = {i.module.replace(".", "/") for i in spec.interfaces if i.id in task.consumes}
    selected = {
        p: c
        for p, c in dependencies.items()
        if any(p in {m + ".py", m + "/__init__.py"} for m in modules)
    }
    return {
        "task": task.model_dump(),
        "requirements": [r.model_dump() for r in requirements],
        "source_excerpts": [asdict(e) for e in index.excerpts if e.source_id in source_ids],
        "interfaces": [
            i.model_dump() for i in spec.interfaces if i.id in task.consumes + task.produces
        ],
        "global_invariants": spec.global_invariants,
        "dependency_files": selected,
        "available_dependency_paths": sorted(dependencies),
        "acceptance_files": [f.model_dump() for f in suite.files if f.path in files],
        "properties": [p.model_dump() for p in suite.properties if set(p.node_ids) & nodes],
        "prior_findings": findings or [],
        "available_source_ids": [e.source_id for e in index.excerpts],
        "source_labels": index.labels,
    }


def resolve_context(
    request: ContextRequest,
    packet: dict,
    index: PaperIndex,
    spec: PaperSpec,
    dependencies: dict[str, str] | None = None,
) -> dict:
    dependencies = dependencies if dependencies is not None else packet["dependency_files"]
    if set(request.paths) - dependencies.keys():
        raise ValueError("Requested path is not an accepted dependency")
    allowed_interfaces = set(packet["task"]["consumes"] + packet["task"]["produces"])
    if set(request.interface_ids) - allowed_interfaces:
        raise ValueError("Requested interface is unrelated to this task")
    excerpts = {e.source_id: e for e in index.excerpts}
    if set(request.source_ids) - excerpts.keys():
        raise ValueError("Requested unknown source ID")
    sources = {e["source_id"]: e for e in packet["source_excerpts"]}
    sources.update({source_id: asdict(excerpts[source_id]) for source_id in request.source_ids})
    return {
        **packet,
        "source_excerpts": list(sources.values()),
        "dependency_files": {
            **packet["dependency_files"],
            **{p: dependencies[p] for p in request.paths},
        },
    }
