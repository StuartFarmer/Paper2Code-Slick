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
    hypothesis: Text
    evidence_artifacts: list[Text] = Field(min_length=1)
    affected_paths: list[Text] = Field(min_length=1)
    proposed_fix: Text
    regression_check: Text
