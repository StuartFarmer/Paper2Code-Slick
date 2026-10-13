"""Typed proposals at model boundaries; acceptance remains controller-owned."""

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


WorkerReply = Annotated[Candidate | ContextRequest | Blocked, Field(discriminator="kind")]


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
    category: Literal["implementation", "test", "spec", "infrastructure"]
    hypothesis: Text
    evidence_artifacts: list[Text] = Field(min_length=1)
    affected_paths: list[Text] = Field(min_length=1)
    proposed_fix: Text
    regression_check: Text


class Limits(BaseModel, extra="forbid"):
    concurrency: int = Field(default=4, ge=1, le=4)
    test_concurrency: int = Field(default=2, ge=1, le=2)
    max_calls: int = Field(default=120, ge=1)
    run_timeout: int = Field(default=3600, ge=1)
    call_timeout: int = 600
    input_bytes: int = 32768
    output_tokens: int = 8192
    schema_repairs: int = 2
    code_fixes: int = 2
    context_requests: int = 2


class RunManifest(BaseModel, extra="forbid"):
    schema_version: Literal[1] = 1
    run_id: Text
    input_hashes: dict[str, str]
    image_id: Text
    platform: Text
    models: dict[str, str]
    output_repo: Text
    limits: Limits = Field(default_factory=Limits)
    plan_hash: str = ""
    suite_hash: str = ""
    accepted_hash: str = ""
    calls_reserved: int = 0
    active_seconds: float = 0
    active_since: float | None = None
    outcome: Literal["incomplete", "complete", "failed", "cancelled"] = "incomplete"


class TaskRecord(BaseModel, extra="forbid"):
    task_id: Text
    plan_hash: str
    state: Literal[
        "pending",
        "ready",
        "implementing",
        "checking",
        "reviewing",
        "repairing",
        "accepted",
        "blocked",
        "cancelled",
    ]
    dependencies: dict[str, str] = Field(default_factory=dict)
    candidate_hash: str = ""
    suite_hash: str = ""
    image_id: str = ""
    generations: int = 0
    schema_repairs: int = 0
    context_requests: int = 0
    fixes: int = 0
    check_artifacts: list[str] = Field(default_factory=list)
    review_artifacts: list[str] = Field(default_factory=list)
    candidate_artifact: str = ""
    diagnosis_artifact: str = ""
    blocker: str = ""


class CallRecord(BaseModel, extra="forbid"):
    id: Text
    role: Text
    model: str
    task_id: str
    attempt: int
    status: Literal["unknown", "completed", "failed", "cancelled"] = "unknown"
    input_bytes: int | None = None
    prompt_artifact: str | None = None
    response_artifact: str | None = None
    started: float
    finished: float | None = None
    measured_tokens: int | None = None
    measured_cost: float | None = None


class CheckSpec(BaseModel, extra="forbid"):
    id: Text
    kind: Literal["syntax", "imports", "pytest", "smoke"]
    targets: list[Text] = Field(min_length=1)
    timeout_seconds: float = Field(default=120, gt=0, le=300)


class ExecutionResult(BaseModel, extra="forbid"):
    check_id: Text
    candidate_hash: str
    dependency_hash: str
    suite_hash: str
    image_id: str
    argv: list[str]
    exit_code: int | None
    status: Literal["passed", "failed", "timeout", "oom", "cancelled", "infrastructure_error"]
    duration_seconds: float
    stdout_artifact: str
    stderr_artifact: str
    output_truncated: bool
    collected_tests: int | None = None
    property_statistics: dict = Field(default_factory=dict)
    replay_complete: bool = True
    failed_nodes: list[str] = Field(default_factory=list)


class RunnerReport(BaseModel, extra="forbid", strict=True):
    kind: Literal["syntax", "imports", "pytest", "smoke"]
    targets: list[str]
    exit_code: int
    collected: list[str]
    passed: list[str]
    failed: list[str]
    skipped: list[str]
    errors: list[str]
    property_statistics: dict = Field(default_factory=dict)


class RequirementEvidence(BaseModel, extra="forbid"):
    status: Literal[
        "tested_method",
        "tested_domain",
        "tested_engineering_choice",
        "deferred_empirical",
        "unresolved",
    ]
    sources: list[SourceRef]
    property_ids: list[str]
    node_ids: list[str]
    execution_artifacts: list[str]
    rationale: str


class RunReport(BaseModel, extra="forbid"):
    outcome: Literal["complete", "incomplete", "failed", "cancelled"]
    generation_complete: bool
    tests_verified: bool
    integration_verified: bool
    requirements: dict[str, RequirementEvidence]
    properties: dict[str, PropertySpec]
    calibration: dict[str, Literal["uncalibrated"]]
    deviations: list[str]
    blocked_tasks: dict[str, str]
    calls_reserved: int
    active_seconds: float
    measured_cost: float | None
    input_hashes: dict[str, str]
    image_id: str
    models: dict[str, str]
    error: str
