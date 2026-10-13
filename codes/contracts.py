"""Small model outputs plus the Docker runner and run settings."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FileTask(BaseModel):
    path: Text
    instructions: Text


class Plan(BaseModel):
    overview: Text
    files: list[FileTask] = Field(min_length=1)


class FileContent(BaseModel):
    path: Text
    content: str


class Revision(BaseModel):
    files: list[FileContent]
    notes: str = ""


class Limits(BaseModel):
    concurrency: int = Field(default=4, ge=1, le=16)
    max_calls: int = Field(default=120, ge=1)
    run_timeout: int = Field(default=3600, ge=1)
    call_timeout: int = 600
    output_tokens: int = 8192
    schema_repairs: int = 2
    code_fixes: int = 2


class RunManifest(BaseModel):
    schema_version: Literal[2] = 2
    run_id: Text
    input_hashes: dict[str, str]
    image_id: Text
    platform: Text
    models: dict[str, str]
    output_repo: Text
    limits: Limits = Field(default_factory=Limits)
    export_hash: str = ""
    export_path: str = ""
    calls_reserved: int = 0
    fixes: int = 0
    active_seconds: float = 0
    active_since: float | None = None
    outcome: Literal["incomplete", "complete", "draft", "failed", "cancelled"] = "incomplete"


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
    coverage: dict = Field(default_factory=dict)
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
    coverage: dict = Field(default_factory=dict)
