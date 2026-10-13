# Proposed Pydantic contracts

Status: design, not installed code. Implements the boundaries in the
[workflow design](2026-10-13-improved-workflow-design.md). Target module:
`codes/contracts.py`. Avoid a generic agent/protocol hierarchy.

Generated objects use `extra="forbid"`; descriptive text is nonblank, but file
content is preserved verbatim. Pydantic validates representation. Python checks
cross-record relationships, source evidence, paths, budgets, and actual results.
The models below are a concrete starting contract, not a mandate to serialize
every internal Python value. Version persisted envelopes with `schema_version=1`.

## Source and planning models

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceRef(BaseModel, extra="forbid"):
    source_id: Text
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: Text


class Requirement(BaseModel, extra="forbid"):
    id: Text
    statement: Text
    basis: Literal["paper", "engineering_choice", "unresolved"]
    claim_kind: Literal["method", "mathematical", "empirical"]
    verification_scope: Literal["v1_required", "deferred_empirical"]
    sources: list[SourceRef]
    rationale: str
    acceptance_criteria: list[Text] = Field(min_length=1)


class Extraction(BaseModel, extra="forbid"):
    requirements: list[Requirement]
    unresolved_references: list[Text]


class Interface(BaseModel, extra="forbid"):
    id: Text
    module: Text
    symbol: Text
    signature: Text
    semantics: Text
    shapes_units_and_time: Text
    state_and_errors: Text


class PaperSpec(BaseModel, extra="forbid"):
    requirements: list[Requirement] = Field(min_length=1)
    interfaces: list[Interface]
    global_invariants: list[Text]
    deviations: list[Text]


class TaskSpec(BaseModel, extra="forbid"):
    id: Text
    objective: Text
    requirement_ids: list[Text] = Field(min_length=1)
    depends_on: list[Text]
    owned_paths: list[Text] = Field(min_length=1)
    consumes: list[Text]
    produces: list[Text]
    acceptance_criteria: list[Text] = Field(min_length=1)


class TaskPlan(BaseModel, extra="forbid"):
    tasks: list[TaskSpec] = Field(min_length=1)
    integration_criteria: list[Text] = Field(min_length=1)
```

Controller checks:

- Source ID and inclusive line span exist in the frozen normalized paper;
  `end_line >= start_line`; quote is present in the cited span. Paper-derived
  requirements require evidence. An engineering choice needs a rationale;
  unsupported paper claims cannot silently become facts.
- Requirement, task, and interface IDs are unique and all references resolve.
- Only empirical claims can be `deferred_empirical`, with an explicit rationale
  recording missing data/protocol/evidence. Scope freezes with the plan; deferral
  cannot satisfy the original claim or resolve a blocking method ambiguity.
- Every binding requirement has an owning task or an explicit blocking/deviation
  entry. Each produced interface has one owner. Consumers depend transitively on
  that owner. Unresolved requirements used by tasks block dispatch.
- DAG is acyclic. Production paths have one owner, are relative and confined,
  and never overlap acceptance tests, controller files, or run metadata.
- `TaskPlan` is frozen and hashed before workers run. Models do not supply trusted
  content hashes or authoritative state transitions.

## Candidate and review models

```python
class FileContent(BaseModel, extra="forbid"):
    path: Text
    content: str


class Candidate(BaseModel, extra="forbid"):
    kind: Literal["candidate"]
    files: list[FileContent] = Field(min_length=1)
    notes: str


class ContextRequest(BaseModel, extra="forbid"):
    kind: Literal["needs_context"]
    source_ids: list[Text]
    interface_ids: list[Text]
    paths: list[Text]
    reason: Text


class Blocked(BaseModel, extra="forbid"):
    kind: Literal["blocked"]
    reason: Text
    affected_ids: list[Text]


WorkerReply = Annotated[
    Candidate | ContextRequest | Blocked, Field(discriminator="kind")
]


class PropertySpec(BaseModel, extra="forbid"):
    id: Text
    requirement_ids: list[Text] = Field(min_length=1)
    node_ids: list[Text] = Field(min_length=1)
    kind: Literal["example", "invariant", "metamorphic", "differential"]
    justification: Text
    domain_and_preconditions: Text
    relation: Text
    oracle_basis: Literal["hand_derived", "independent_reference", "necessary_relation"]
    oracle_evidence: Text
    tolerance: Text


class TestSuite(BaseModel, extra="forbid"):
    files: list[FileContent] = Field(min_length=1)
    properties: list[PropertySpec] = Field(min_length=1)
    task_targets: dict[str, list[Text]]
    integration_targets: list[Text]


class Finding(BaseModel, extra="forbid"):
    id: Text
    severity: Literal["blocking", "advisory"]
    category: Literal["spec", "interface", "behavior", "test", "quality"]
    requirement_ids: list[Text]
    property_ids: list[Text]
    evidence_artifact_ids: list[Text]
    artifact: Text
    line: int | None = Field(default=None, ge=1)
    observation: Text
    expected_behavior: Text
    suggested_check: Text


class Review(BaseModel, extra="forbid"):
    verdict: Literal["pass", "revise", "blocked"]
    findings: list[Finding]
    unresolved_requirement_ids: list[Text]


class Diagnosis(BaseModel, extra="forbid"):
    hypothesis: Text
    evidence_artifacts: list[Text] = Field(min_length=1)
    affected_paths: list[Text] = Field(min_length=1)
    proposed_fix: Text
    regression_check: Text
```

Implementation and repair prompts both return `WorkerReply`. Test authoring
returns `TestSuite`; specification, test, task, fix, and fidelity review operations
return `Review`. They have separate templates and input packets despite reusing
the same result shape. Diagnosis is its own operation; schema repair is separately
bounded and carries the required output schema.

`PaperSpec`, `TaskPlan`, and `TestSuite` are also the fragment shapes used in
bounded generation. Controller metadata identifies each fragment's requirement
group/task and allowed IDs; models cannot overwrite entries outside that scope.
No new fragment wrapper is needed. The controller merges by ID, checks global
coverage and graph/interface consistency, and serializes the assembled artifact.
A task test fragment has one `task_targets` entry and no integration targets;
an integration fragment has no task targets and nonempty integration targets.
The final assembled suite must have targets for every task and at least one
integration target. `plan_tasks` fragments state local integration criteria;
cross-component criteria are reconciled separately against both interfaces.

V1 candidate updates are full replacement content for owned files, not a custom
patch language. No delete or rename action. Apply all files atomically to a new
candidate snapshot after validation. Reject duplicate paths, symlinks, traversal,
non-owned files, files over 16,384 UTF-8 bytes, or a bundle over 32,768 bytes.
If needed, split the task before retrying; do not clip source code.

Test files live under `tests/acceptance/`, cannot supply pytest plugins,
`conftest.py`, or runner configuration, and cannot install packages. Node IDs must
resolve to those test files; no free-form shell options. Test review checks for
skip/xfail, vacuous assertions, and unsupported assumptions. Python preflight
rejects obvious skip/xfail markers; code review and external fixtures remain
necessary because syntax scans cannot establish test quality.

Property IDs are unique across fragments. Their requirement and node IDs must
resolve inside the fragment's permitted scope, and every required behavior must
have a property-to-execution link. An `example` is sufficient where generated
properties add no value. Evidence quotes remain on requirements; do not duplicate
them. Validate reference artifacts exist and hash them before freezing. Python
checks links and results; the reviewer checks whether the relationship follows
from the sources, preconditions and declared engineering choices. It cannot infer
semantic validity from a nonempty field. See the
[research synthesis](../../research_property_fidelity/integration.md).

Wrap every generated record in controller-owned metadata: call ID, role/model,
task ID, attempt, input hash, output hash, and timestamps. Never accept a model's
claim of having run a command as an `ExecutionResult`.

## Execution and persisted records

The controller alone produces the following Pydantic records. These are storage
and tool-result boundaries, not additional model prompt outputs.

| Record | Required fields and meaning |
| --- | --- |
| `CheckSpec` | `id`, `kind: syntax/imports/pytest/smoke`, `targets: list[str]`, `timeout_seconds`. Registered before task execution; runner builds argv. |
| `ExecutionResult` | `check_id`, `candidate_hash`, `dependency_hash`, `suite_hash`, `image_id`, `argv`, `exit_code: int or null`, `status: passed/failed/timeout/oom/cancelled/infrastructure_error`, `duration_seconds`, `stdout_artifact`, `stderr_artifact`, `output_truncated`, `collected_tests: int or null`. |
| `TaskPacket` | `task`, `source_excerpts`, `interfaces`, `global_invariants`, `dependency_files`, `acceptance_files`, `prior_findings`. Constructed from frozen artifacts and checked after complete rendering. |
| `TaskRecord` | `task_id`, `plan_hash`, `state`, dependency hashes, candidate/test/image hashes, counters for generations/schema repairs/context requests/fixes, check and review artifact IDs, blocker reason. |
| `RunManifest` | `schema_version`, `run_id`, source/code/prompt/lock/plan hashes, image ID/platform, role model IDs, limits, timestamps, journal sequence, accepted snapshot hash, run outcome. No secret values. |
| `CallRecord` | `id`, role/model, task/attempt, prompt and raw-response artifact paths, times, status, input bytes, optional measured token usage/cost, optional clearly labelled estimates. Failed/cancelled/unknown calls count. |
| `RunReport` | generation/test/integration outcomes, requirement-to-evidence mapping, deviations/unresolved requirements, blocked tasks, measured checks/cost/duration, provenance links. |

Extend `ExecutionResult` with optional property statistics and replay-artifact
references: valid/invalid case counts, stop reason, health/flakiness outcome and
counterexample completeness. Unknown counts stay null. The trusted runner owns
these values; model prose is not execution evidence. `RunManifest` also freezes
the Hypothesis profile and dependency versions. `RunReport` maps requirement ->
property -> node -> matching execution and lists deferred empirical claims.
Calibration uses the existing `CheckSpec`/`ExecutionResult` records on separately
hashed reference/fault fixtures, not another execution backend or result schema.

Task states: `pending -> ready -> implementing -> checking -> reviewing -> accepted`.
From checking/reviewing, `repairing` can return to implementing; any active state
can become `blocked` or `cancelled`. A dependency change returns affected accepted
tasks to `pending` with explicit invalidation evidence. Review verdict alone
never performs a state transition.

Accept only when the required check set is complete, each check passes on the
same candidate/dependency/suite/image hashes, pytest collects at least one test,
the review has no blocking findings, and coverage has no unresolved binding
requirement. A contradiction such as `verdict=pass` plus a blocking finding is an
invalid review and consumes its bounded schema/semantic correction allowance.

Persist authoritative state snapshots atomically and append diagnostic events
afterward. On restart, state snapshots are authoritative; a truncated final
journal line cannot invent or erase acceptance. Hold a run lock for the process
lifetime. An accepted artifact without a completed state transaction is pending
until its matching evidence is reconciled; it is never accepted just because a
file exists.

## Worked task shape

```json
{
  "id": "fit-training-scales",
  "objective": "Fit per-feature scales using training observations only",
  "requirement_ids": ["causal-preprocessing"],
  "depends_on": ["dataset-contract"],
  "owned_paths": ["feature_scaling.py"],
  "consumes": ["dataset-split-v1"],
  "produces": ["feature-scales-v1"],
  "acceptance_criteria": [
    "Changing validation/test extremes cannot change fitted scales",
    "Transform uses the frozen training scales for every split",
    "Zero training scale follows the documented finite-output policy"
  ]
}
```

This example is an engineering deviation, not literal AlphaEvolve replication:
the supplied `paper/main.tex:301` explicitly normalizes over all time steps. It
requires `basis=engineering_choice`, `claim_kind=method`,
`verification_scope=v1_required`, a rationale and a recorded deviation from the paper. A literal
replication task instead tests the stated full-period maximum. Never enforce
both incompatible contracts on one implementation. Actual array signatures
belong in `Interface` records.

## Implementation status (2026-10-13)

The verified V1 controller, CLI, Docker executor, prompts and offline evaluation
fixtures are implemented on `improved`. Use the current README for executable
commands. Task 11's paid GPT-OSS stages and independent human adjudication have
not run; an OpenRouter key is absent in the development environment.

Implementation amendments: `codes/agent.py` owns the workflow and
`codes/workflow.py` the CLI; `run_verified` handles exceptions outside Slick's
restricted workflow syntax. The initial CPU wheel lock is Linux ARM64.
Oversized interface registries or indivisible packets block instead of silently
truncating evidence; automatic pairwise repartition is not implemented. Test/spec
corrections require a new reviewed run; only implementation/schema repair is
automatic. Component/full trial scientific adjudication remains manual.
These boundaries narrow the original plan and are not evidence that its entire
evaluation ladder or all proposed acceptance cases have been completed.
