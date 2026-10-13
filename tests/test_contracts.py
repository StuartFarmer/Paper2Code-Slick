import copy

import pytest
from pydantic import TypeAdapter, ValidationError

from codes.contracts import PaperSpec, Review, TaskPlan, WorkerReply
from codes.contracts import TestSuite as Suite
from codes.planning import validate_plan, validate_review, validate_suite


def spec_plan():
    spec = PaperSpec.model_validate(
        {
            "requirements": [
                {
                    "id": "r",
                    "statement": "Compute f",
                    "basis": "engineering_choice",
                    "claim_kind": "method",
                    "verification_scope": "v1_required",
                    "sources": [],
                    "rationale": "Numerical fixture",
                    "acceptance_criteria": ["f(2)=4"],
                }
            ],
            "interfaces": [
                {
                    "id": "i",
                    "module": "a",
                    "symbol": "f",
                    "signature": "f(x: float) -> float",
                    "semantics": "square",
                    "shapes_units_and_time": "scalar",
                    "state_and_errors": "pure",
                }
            ],
            "global_invariants": [],
            "deviations": [],
        }
    )
    tasks = [
        {
            "id": name,
            "objective": "Compute",
            "requirement_ids": ["r"],
            "depends_on": deps,
            "owned_paths": [name + ".py"],
            "consumes": consumes,
            "produces": produces,
            "acceptance_criteria": ["f(2)=4"],
        }
        for name, deps, consumes, produces in [
            ("a", [], [], ["i"]),
            ("b", ["a"], ["i"], []),
            ("c", ["a"], ["i"], []),
            ("d", ["b", "c"], ["i"], []),
        ]
    ]
    return spec, TaskPlan(tasks=tasks, integration_criteria=["consistent"])


def suite_for(plan):
    files = [
        {
            "path": f"tests/acceptance/{t.id}/test_method.py",
            "content": "def test_value():\n    assert 2 + 2 == 4\n",
        }
        for t in plan.tasks
    ]
    nodes = {t.id: [f["path"] + "::test_value"] for t, f in zip(plan.tasks, files)}
    return Suite(
        files=files,
        task_targets=nodes,
        integration_targets=nodes["d"],
        properties=[
            {
                "id": "p-" + t,
                "requirement_ids": ["r"],
                "node_ids": n,
                "kind": "example",
                "justification": "fixture",
                "domain_and_preconditions": "scalar",
                "relation": "f(2)=4",
                "oracle_basis": "hand_derived",
                "oracle_evidence": "2*2=4",
                "tolerance": "exact",
            }
            for t, n in nodes.items()
        ],
    )


def test_diamond_plan_and_property_evidence_roundtrip():
    spec, plan = spec_plan()
    validate_plan(spec, plan)
    suite = suite_for(plan)
    validate_suite(spec, plan, suite)
    assert Suite.model_validate_json(suite.model_dump_json()) == suite
    assert spec.interfaces[0].shapes_units_and_time == "scalar"


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_field",
        "duplicate_id",
        "cycle",
        "missing_dependency",
        "duplicate_owner",
        "path_alias",
        "missing_interface",
        "missing_ancestor",
        "missing_requirement",
        "unresolved",
        "false_deferral",
        "missing_evidence",
    ],
)
def test_invalid_plan_is_rejected(fault):
    spec, plan = spec_plan()
    raw = plan.model_dump()
    if fault == "unknown_field":
        raw["trust_me"] = True
    elif fault == "duplicate_id":
        raw["tasks"][1]["id"] = "a"
    elif fault == "cycle":
        raw["tasks"][0]["depends_on"] = ["d"]
    elif fault == "missing_dependency":
        raw["tasks"][1]["depends_on"] = ["unknown"]
    elif fault == "duplicate_owner":
        raw["tasks"][1]["owned_paths"] = ["a.py"]
    elif fault == "path_alias":
        raw["tasks"][1]["owned_paths"] = ["src/../a.py"]
    elif fault == "missing_interface":
        raw["tasks"][0]["produces"] = ["unknown"]
    elif fault == "missing_ancestor":
        raw["tasks"][1]["depends_on"] = []
    elif fault == "missing_requirement":
        spec.requirements.append(spec.requirements[0].model_copy(update={"id": "uncovered"}))
    elif fault == "unresolved":
        spec.requirements[0].basis = "unresolved"
    elif fault == "false_deferral":
        spec.requirements[0].verification_scope = "deferred_empirical"
    elif fault == "missing_evidence":
        spec.requirements[0].basis = "paper"
    with pytest.raises(ValueError):
        validate_plan(spec, TaskPlan.model_validate(raw))


@pytest.mark.parametrize(
    "fault",
    ["node", "requirement", "property", "skip", "settings", "empty", "target", "uncovered_task"],
)
def test_invalid_suite_is_rejected(fault):
    spec, plan = spec_plan()
    suite = suite_for(plan)
    if fault == "node":
        suite.properties[0].node_ids = ["tests/acceptance/missing.py::test_no"]
    elif fault == "requirement":
        suite.properties[0].requirement_ids = ["unknown"]
    elif fault == "property":
        suite.properties.append(copy.deepcopy(suite.properties[0]))
    elif fault == "skip":
        suite.files[0].content = "import pytest\n@pytest.mark.skip\ndef test_value(): pass\n"
    elif fault == "settings":
        suite.files[
            0
        ].content = (
            "from hypothesis import settings\n@settings(max_examples=1)\ndef test_value(): pass\n"
        )
    elif fault == "empty":
        suite.properties.clear()
    elif fault == "target":
        suite.task_targets["a"] = ["--collect-only"]
    elif fault == "uncovered_task":
        del suite.task_targets["b"]
    with pytest.raises(ValueError):
        validate_suite(spec, plan, suite)


def test_false_passing_review_and_malformed_worker_replies_rejected():
    with pytest.raises(ValueError):
        validate_review(Review(verdict="pass", findings=[], unresolved_requirement_ids=["r"]))
    with pytest.raises(ValidationError):
        TypeAdapter(WorkerReply).validate_python({"kind": "accepted", "files": []})
