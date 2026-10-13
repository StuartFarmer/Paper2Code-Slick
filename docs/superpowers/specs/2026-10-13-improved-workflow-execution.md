# Tools, Docker, and execution boundaries

Status: proposal. See the [workflow design](2026-10-13-improved-workflow-design.md)
and [contracts](2026-10-13-improved-workflow-contracts.md).

## What rsikit contributes

Inspected `../rsikit/Dockerfile`, `.dockerignore`, `scripts/run`,
`tests/test_container_launch.py`, `tests/container_smoke.py`, and its archived
containerized-application design. Rsikit uses a cached build, a foreground
`docker run`, mounted durable outputs, read-only root filesystem, temporary HOME,
resource limits, signal propagation, and recorded image identity. Its whole
application has network access and API credentials; generated policy processes
are lifecycle-isolated, not isolated from those credentials.

Adopt the small launcher and lifecycle patterns. For Paper2Code V1, run the
trusted API/controller process on the host and only generated programs/tests
inside Docker. This avoids a Docker socket inside an application container.
V1 verified runs use OpenRouter API models; host Codex/Claude CLI adapters are
rejected because their internal tool execution and model calls bypass these limits. Generated code receives neither
API credentials nor the full repository/run store. Docker is the only execution
backend; no host fallback, Compose, Docker-in-Docker, or RPC service.

## Necessary tools

No provider-native tool calling is required. Slick generates typed proposals;
Python dispatches the operations below. A future tool-enabled provider can expose
these same operations, but that is not part of V1.

| Operation / proposed signature | Owner and limits |
| --- | --- |
| `build_packet(task: TaskSpec, store: RunStore) -> TaskPacket` | Controller selects excerpts, contract definitions, accepted dependencies, and tests. Validate rendered byte budget. |
| `resolve_context(request: ContextRequest, task: TaskSpec, store: RunStore) -> TaskPacket` | Only known source IDs, dependency interfaces, and allowed dependency paths. At most two expansions; no filesystem crawling. |
| `stage_candidate(task: TaskSpec, candidate: Candidate, workspace: Path) -> str` | Controller validates paths/ownership/size and returns its content hash. No model-selected output root. |
| `run_check(check: CheckSpec, workspace: Path, suite: Path, image: str) -> ExecutionResult` | Docker runner builds fixed argv, enforces deadlines, captures evidence, and removes the container. Async function. |
| `read_evidence(artifact_id: str, start_line: int, max_lines: int) -> str` | Controller supplies bounded logged evidence by registered artifact ID, not an arbitrary host path. Default 100 lines, maximum 200. |
| `accept_task(task_id: str, evidence_ids: list[str], store: RunStore) -> None` | Controller-only gate verifies hashes, required checks, and review findings before publishing. |

Model-facing context requests are structured data, not shell commands. Source
search in V1 is deterministic ID/label lookup over the normalized paper; add
semantic retrieval only if the first evaluation shows that lookup is inadequate.
Only the controller imports application code. Generated modules are never imported
in the host process, including during test discovery or dependency inspection.

## Execution image

Proposed files: `docker/Dockerfile`, `docker/requirements.lock`,
`docker/check.py`, root `.dockerignore`, and `scripts/build-executor.sh`.

- Base: `python:3.11-slim`; resolve and record the exact image ID/digest and native
  architecture at build time. Test ARM64 on this Mac; avoid x86 emulation by default.
- First profile: pytest, Hypothesis, NumPy, pandas, SciPy, PyYAML, and CPU-only PyTorch for
  constructor/training smoke. Pin tested dependency versions and hashes in the
  executor lock during implementation, not speculative versions in this plan.
- Install dependency layers before copying `docker/check.py`; do not copy the
  paper, API clients, outputs, user home, or the whole checkout into the image.
- Verify scientific imports during image build. Build uses network; execution
  does not. Generated requirements never trigger an automatic pip install.
- A task needing an unavailable dependency returns blocked; changing the image
  is an explicit run-input change. CPU smoke is not full training. Docker Desktop
  on macOS does not provide the existing host MPS training path in this design.
- Use `.dockerignore` as an allowlist for the Dockerfile, lock, and trusted runner.
  Exclude `.env*`, keys, `.git`, `.venv`, source data, outputs, and logs.

The application continues to use PyPI `slick-ai[openai]` in the user's uv
environment. Declare Pydantic directly if its API is imported directly. Pytest
is a dev dependency for application checks; generated code dependencies belong
to the separate executor image. No Docker Python SDK is needed: standard-library
async subprocesses execute Docker with argv lists and `shell=False`.

## Per-check container

Illustrative command, to be built as an argv list by `codes/execution.py`:

```bash
docker run --name p2c-RUN-TASK-ATTEMPT --init \
  --user UID:GID --read-only --network none \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 128 --cpus 1 --memory 2g --memory-swap 2g \
  --tmpfs /tmp:rw,exec,nosuid,size=256m \
  --mount type=bind,src=CANDIDATE_SNAPSHOT,dst=/workspace,readonly \
  --mount type=bind,src=FROZEN_SUITE,dst=/acceptance,readonly \
  --workdir /workspace \
  --env HOME=/tmp --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 --env MKL_NUM_THREADS=1 \
  EXECUTOR_IMAGE_ID python /runner/check.py CHECK_SPEC_JSON
```

Placeholders are controller-selected values, not raw model output. The name is
generated from safe internal IDs. `CHECK_SPEC_JSON` contains only registered
check kind/targets; the trusted runner validates it again. Supply an explicit
clean environment; never use Docker `--env-file` or forward API keys to checks.
No privileged mode, host network, Docker socket, or source-data write mount.

Default limits are per check: 1 CPU, 2 GiB memory, 128 PIDs, 256 MiB tmpfs,
120 seconds; two checks may run concurrently. A registered end-to-end smoke
check may use 300 seconds, still under the run deadline. Limit captured stdout
and stderr to 1 MiB each, drain excess without retaining it, and mark truncation.
Send at most 8 KiB of focused failure evidence to a model before packet budgeting.

The host waits for the container, obtains its exit state (including OOM), then
removes it in `finally`. Do not use auto-removal before inspection. Timeout,
cancellation, and SIGINT must force-remove the named container and await cleanup;
killing only the Docker client is insufficient. Stale containers carry run/task
labels and are removed on explicit resume after verifying they belong to that run.

No task-produced binary artifact export is needed in V1; capture diagnostic text
and keep immutable source/test snapshots on the host. Tests write temporary data
under `/tmp`. Add an explicit bounded export protocol only if later evaluations
need trained weights or figures. Prevent a generated test from writing into a
shared host output mount.

## Check semantics and trust limits

Registered check kinds map to fixed entry points:

- `syntax`: compile each owned Python file without writing pycache.
- `imports`: import named generated modules inside the container.
- `pytest`: run frozen acceptance node IDs with cache disabled and reject zero
  collected tests. No model-controlled pytest flags/plugins/config discovery;
  set an explicit trusted config and `--noconftest`. The suite snapshot preserves
  `tests/acceptance/` beneath its root, so a registered node ID
  `tests/acceptance/test_scaling.py::test_train_only` maps to
  `/acceptance/tests/acceptance/test_scaling.py::test_train_only`. Set the generated
  import root explicitly to `/workspace`; clear inherited pytest options.
- `smoke`: run an approved integration acceptance test with synthetic data and
  the longer deadline; not an arbitrary shell script or model-selected command.

The runner produces machine-readable test results plus exit status. It checks
the collected required targets, failures, skips, and errors; a swallowed exception
or `sys.exit(0)` before collection is not a passing suite. Unit-test the result
parser against missing/truncated reports. Record `infrastructure_error` separately
from a failed scientific assertion.

### Property-test profile and evidence

Before importing acceptance tests, the trusted runner loads a pinned Hypothesis
profile: `max_examples=100`, `derandomize=True`, `database=None`, `deadline=None`,
`print_blob=True`, explicit/generate/shrink phases, health checks unsuppressed.
These are initial engineering defaults to calibrate, not measured optima. Keep
plugin autoload disabled and explicitly load `-p hypothesispytest` plus the
trusted result plugin; verify that entry point in the pinned image. Generated
tests cannot provide plugins or unapproved per-test profile overrides.

Bound strategies' shapes and magnitudes and reset mutable state per case.
`max_examples` does not cap all executions, and shrinking can take additional
time; the existing Docker deadline remains the hard boundary. Record profile,
Python/Hypothesis/library versions, architecture and RNG settings. Deterministic
generation does not control external randomness or guarantee cross-version replay.

Capture per-node valid/invalid counts and stop reason where supported, health
and flakiness failures, and failing inputs/replay text in bounded evidence.
Unknown statistics remain null; a small exhausted finite domain can be valid.
Timeout, unsatisfiable generators or health-check failures cannot satisfy a
property. Truncated counterexample evidence is marked incomplete. Adjudicated
regressions may become explicit examples only through reviewed suite revision
and invalidation; no writable shared Hypothesis database is mounted.

Curated correct-reference and semantic-fault checks use separately hashed
snapshots through this same runner. A relevant assertion failure counts as a
detected fault; import errors, crashes and resource failures are inconclusive.
No mutation framework or runtime dependency installer is added. Initial external
calibration is capped at six reference/fault pairs (12 checks), sharing existing
active-time and concurrency limits. Uncalibrated properties are reported honestly.
See [research and primary sources](../../research_property_fidelity/integration.md).

Tests and production code share a Python process for ordinary pytest checks.
They are therefore not a cryptographic defense against deliberately adversarial
code fabricating results. Read-only suites, trusted runner/config, review, and
independent external acceptance cases address ordinary generated-code failures;
do not claim stronger anti-cheating guarantees. A separate black-box evaluator
can be added if experiments reveal test tampering, with its own design.

The read-only snapshot is the **dependency closure plus the task's candidate**,
not whichever files happen to be in a shared output directory. Every check records
the complete snapshot hash and suite/image identities. Host Python never executes
pytest over generated code, even for collection.

## Launch surface and failure behavior

Proposed commands, not implemented yet:

```bash
./scripts/build-executor.sh
export OPENROUTER_API_KEY="<replacement-key>"
uv run python -m codes.workflow PAPER_PATH \
  --model openai/gpt-oss-120b:nitro \
  --executor-image paper2code-executor:local \
  --concurrency 4 --test-concurrency 2 \
  --max-calls 120 --run-timeout 3600 \
  --output-dir outputs/AlphaEvolve_improved \
  --output-repo-dir outputs/AlphaEvolve_improved_repo
```

Keep existing input/model/output flag names. Reject `codex`/`claude` in the
verified workflow before dispatch; the first default is the explicit OpenRouter
model `openai/gpt-oss-120b:nitro`. Update convenience scripts consistently. New runs require unused output paths;
fail on collisions instead of overwriting a previous experiment. Export the final
accepted repository only after integration verification. Partial work remains
under the run directory with an incomplete report. Preserve the current workflow
as a frozen evaluation baseline, not a second maintained runtime mode.

`--resume RUN_DIR` reopens the frozen manifest and uses its paths/settings; it is
mutually exclusive with a new paper or overriding generation/execution settings.
Do not auto-upgrade prompts, model IDs, or dependencies on resume. Validate
Docker daemon/image availability and render every prompt before the first paid
call. Missing credentials produce a provider setup error without printing values.

CLI success is exit 0 only for a fully accepted and integration-verified run;
blocked, budget-exhausted, and failed runs exit nonzero with a report path.
SIGINT returns 130 after cleanup. When documenting `tee`, enable shell `pipefail`
so a logger's successful exit does not hide workflow failure.

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
