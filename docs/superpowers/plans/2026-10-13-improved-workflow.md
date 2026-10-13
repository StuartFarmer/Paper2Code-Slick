> Historical design: superseded by the simple plan → files → tests → repair workflow.
> See the repository README for current behavior.

# Improved Paper2Code implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax. Implementation was subsequently authorized by “can we begin development?”.

**Goal:** Generate and verify research code through bounded, short-context tasks,
then evaluate the complete flow with `openai/gpt-oss-120b:nitro`.

**Architecture:** One Slick `PaperCoder` orchestrates source extraction, typed
planning, independently authored acceptance tests, parallel candidate generation,
Docker verification, fresh reviews, and bounded fixes. Python owns the task graph,
file publication, budgets, durable state, and completion. The API controller stays
on the host; generated code runs only in credential-free execution containers.

**Tech Stack:** Python 3.10+ host, Slick from PyPI, Pydantic 2, Jinja, asyncio,
standard-library filesystem/subprocess tools, pytest, Docker/Python 3.11 executor.

**Spec:** [Design](../specs/2026-10-13-improved-workflow-design.md),
[contracts](../specs/2026-10-13-improved-workflow-contracts.md),
[tools and Docker](../specs/2026-10-13-improved-workflow-execution.md).

Research amendment: [scientific fidelity + property testing](../../research_property_fidelity/integration.md).
GEPA is V2; this plan adds no prompt optimizer or optimization budget.

## Global Constraints

- Host Python remains 3.10+; the first Linux execution image uses Python 3.11.
- All initial model roles use `openai/gpt-oss-120b:nitro`; no silent stronger-model fallback.
- At most four concurrent model calls and two concurrent Docker checks per run.
- Each provider call has a 600-second timeout and an 8,192-output-token ceiling.
- Fully rendered model input is limited to 32,768 UTF-8 bytes, including schema,
  excerpts, repair evidence, and any history.
- At most two schema repairs per logical generation, two code-fix rounds per
  task, and two additional context requests per task. These share the run budget.
- Default run limits: 120 dispatched model calls and 3,600 seconds elapsed.
- Required Docker checks must run; Docker absence never selects a host-execution fallback.
- Models propose changes; the controller owns acceptance, writes, test commands,
  budgets, and durable state. A model cannot set a task to accepted.
- Never overwrite the existing AlphaEvolve run/output directories during development
  or benchmarking. Preserve the user's staged submodule and unrelated local files.

## Review Focus

1. A declared-passing review with failed/missing/stale test evidence must not
   accept a task. Covered by Tasks 2, 7, 8, and 10.
2. Parallel workers touching shared paths or consuming changed dependencies must
   not corrupt or silently reuse code. Covered by Tasks 2, 8, and 9.
3. Infinite loops, descendant processes, OOM, oversized output, or Ctrl-C must
   leave no active executor containers. Covered by Tasks 5 and 10.
4. Prompt/schema edits or a crash during publication must not create false
   completion or reset budgets on resume. Covered by Tasks 4, 6, and 10.
5. Tests that mirror an incorrect implementation, skip work, or enforce an
   unsupported scientific assumption must not count as verification. Distinguish
   literal paper behavior from safer engineering deviations and deferred empirical
   claims. Covered by Tasks 2, 6, 7, and 11.

## File structure and dependency order

| File | Responsibility |
| --- | --- |
| `codes/workflow.py` | Owning class, decorated operations, orchestration, CLI |
| `codes/contracts.py` | Typed generated and persisted boundaries |
| `codes/paper.py` | Existing input loading plus source indexing/span maps |
| `codes/planning.py` | Source/plan consistency checks and DAG readiness |
| `codes/context.py` | Bounded task/review/repair packets |
| `codes/store.py` | Immutable artifacts, atomic task state, lock, budgets |
| `codes/execution.py` | Candidate staging and Docker lifecycle/checks |
| `codes/prompts/*.j2` | Operation-specific, locally owned prompts |
| `docker/{Dockerfile,requirements.lock,check.py}` | Frozen CPU executor and trusted check runner |
| `scripts/build-executor.sh`, `.dockerignore` | Cached image build with a narrow build context |
| `tests/providers.py`, `tests/test_*.py` | Shared scripted provider and behavioral regression checks |
| `eval/{fixtures,acceptance}/`, `eval/run.py` | Independent evaluation inputs/checks and experiment driver |
| `NOTICE`, `third_party/superpowers-LICENSE` | Adapted-prompt provenance and attribution |

Tasks 1–4 establish contracts/state; Task 5 can proceed independently after Task 2.
Task 6 needs Tasks 2–4; Task 7 needs Tasks 5–6. Tasks 8–11 follow in order.
For initial implementation, prefer sequential edits to `codes/workflow.py` to
avoid contributor conflicts. Parallelism in the product is separately tested.

## Task 1: Preserve the baseline and stabilize project setup

**Files:** `pyproject.toml`, `uv.lock`, `eval/run.py`, `tests/test_baseline.py`.
**Consumes:** current working source, prompts, requirements and uv metadata.
**Produces:** `snapshot_baseline(destination: Path) -> dict[str, str]`, a file-to-
SHA256 manifest over an explicit source/prompt/dependency allowlist.

- [ ] Write `test_baseline_snapshot_excludes_outputs_and_secrets`: create dummy
  `.env`, log, and output paths; assert none enters the snapshot. Assert modified
  prompt bytes change its hash even at the same Git revision.
- [ ] Run `uv run --with pytest python -m pytest tests/test_baseline.py -q` and
  verify the expected missing implementation failure.
- [ ] Implement the snapshot into an unused evaluation directory. Record Git
  revision and dirty-source hashes. Preserve the existing behavior as an artifact,
  not a second application mode. Declare direct runtime dependencies explicitly;
  keep pytest in a dev group, retain PyPI Slick and Python 3.10 support.
- [ ] Run the focused test and current workflow regression suite. Ensure the
  baseline contains the existing JSON healer and records that experimental change.
- [ ] Commit only task-owned setup/baseline files; do not sweep unrelated staged files.

## Task 2: Define contracts and cross-record validation

**Files:** `codes/contracts.py`, `codes/planning.py`, `tests/test_contracts.py`.
**Consumes:** the companion contracts document.
**Produces:** its named models; `validate_plan(spec: PaperSpec, plan: TaskPlan) -> None`.

- [ ] Write parameterized tests for unknown fields, malformed `WorkerReply`,
  invalid review verdict/finding combinations, duplicate paths/IDs, missing
  dependencies, cycles, multiple owners, unresolved consumed interfaces, and
  uncovered requirements. Assert each is rejected before a model worker runs.
- [ ] Run `uv run --with pytest python -m pytest tests/test_contracts.py -q` (RED).
- [ ] Implement representation models and pure semantic checks. Use existing
  `output_path` behavior for filesystem boundaries; do not weaken its symlink
  checks. Keep source/code content unmodified during validation.
- [ ] Add `Requirement.claim_kind`/`verification_scope`, `PropertySpec` on
  `TestSuite`, and finding property/evidence links. Reject dangling property/node
  IDs, missing required behavior coverage, and deferral of binding method
  ambiguities. Preserve explicit empirical deferral reasons and engineering
  deviations; nonempty fields do not prove scientific entailment.
- [ ] Verify a three-task diamond graph is valid and accepted contracts round-trip
  through JSON without losing shape/time/source metadata; run the focused suite.
- [ ] Commit contracts, checks, and tests together.

## Task 3: Index source evidence and validate extracted requirements

**Files:** `codes/paper.py`, `codes/planning.py`, `tests/test_paper.py`.
**Consumes:** existing `load_paper`, `SourceRef`, `Extraction`, `PaperSpec`.
**Produces:** `index_paper(path: Path) -> PaperIndex` and
`validate_sources(extraction: Extraction, index: PaperIndex) -> None`.
`PaperIndex` is an internal dataclass holding normalized text, original-location
mapping, and excerpt IDs/spans; it is not another LLM response model.

- [ ] Test Markdown headings, LaTeX equations/labels, JSON body text, a section
  over 12,288 bytes, an unresolved include, Unicode, and invented/out-of-range quotes.
- [ ] Run the paper tests and existing loader tests; confirm intended RED failures.
- [ ] Implement stable normalized line numbering, paragraph-aware splitting,
  provenance mapping, label lookup, and exact quote/span validation. Preserve
  original input bytes. Mark unresolved includes; do not read arbitrary includes.
- [ ] Assert splitting preserves all source text and stable IDs across identical
  inputs. An oversized indivisible block is explicitly blocked, never truncated.
- [ ] Commit indexing and regression tests.

## Task 4: Store artifacts, budgets, and resumable state

**Files:** `codes/store.py`, `tests/test_store.py`.
**Consumes:** `RunManifest`, `TaskRecord`, `CallRecord`, and content hashes.
**Produces:** `RunStore.create(root, manifest)`, `RunStore.open(root)`,
`save_artifact(relative_path, content) -> str`, `save_task(record) -> None`,
`reserve_call(role, task_id) -> str`, and `check_budget() -> None`.

- [ ] Test output collisions, concurrent run locking, crash before/after atomic
  publication, a truncated event tail, changed prompts, unknown call outcome,
  and attempted budget reset on restart.
- [ ] Run `tests/test_store.py` (RED), then implement immutable artifact writes,
  atomic state snapshots, a single-process run lock, and controller-only events.
- [ ] Reserve call budget before dispatch and persist counters before provider
  execution. Derive state from committed snapshots; logs never invent acceptance.
  Persist cumulative elapsed time; resume does not reset total allowed active time.
- [ ] Run tests; verify a locked run cannot start a second scheduler and completed
  matching tasks do not cause new provider calls on resume.
- [ ] Commit store and tests.

## Task 5: Build the isolated execution backend

**Files:** Docker/build files, `codes/execution.py`, `tests/test_execution.py`,
`tests/test_docker_integration.py`.
**Consumes:** `CheckSpec`, candidate/suite snapshots, existing safe-path helper.
**Produces:** `stage_candidate(...) -> str` and async `run_check(...) -> ExecutionResult`
with the exact signatures in the execution document.

- [ ] Write launcher tests using a fake Docker executable: preserve paths with
  spaces, argv and exit status; omit credentials; inspect before removal; reject
  arbitrary flags/targets. Test ownership/path/size rejection before Docker starts.
- [ ] Run focused tests (RED); implement argv construction, bounded stream drains,
  deadlines, inspect/remove cleanup, and trusted check-target mapping.
- [ ] Build the native image with pinned executor dependencies and import checks.
  Record its ID, lock hash, and platform; no model-generated requirements install.
- [ ] Include Hypothesis and load the trusted profile before test imports, with
  explicit plugin allowlisting. Check known-counterexample shrinking/replay,
  impossible generators, flaky state, small exhausted domains, timeout, settings
  overrides and truncated replay output. Save measured statistics or nulls;
  `max_examples` is not the execution timeout. Keep existing resource limits.
- [ ] Run real Docker tests for pass/fail/zero tests, timeout, a spawned descendant,
  OOM, output flood, read-only mounts, secret absence, network isolation, and
  cancellation. Assert no labelled containers remain after every case. Unit-test
  forged/missing/truncated runner result records as failures.
- [ ] Commit executor, reproducible lock, build script, and checks. Docker absence
  is a failed required check for this task, not grounds to claim completion.

## Task 6: Adapt prompts and construct bounded context

**Files:** `codes/context.py`, `codes/workflow.py`, `codes/prompts/`,
`NOTICE`, `third_party/superpowers-LICENSE`, `tests/test_prompts.py`.
**Consumes:** contracts, source index, accepted snapshots, Superpowers templates.
**Produces:** `build_packet(...)`, `resolve_context(...)`, and decorated operations
`extract_requirements -> Extraction`, `reconcile_spec -> PaperSpec`,
`plan_tasks -> TaskPlan`, `review_spec -> Review`, `author_tests -> TestSuite`,
`review_tests -> Review`, `implement_task -> WorkerReply`, `review_task -> Review`,
`diagnose -> Diagnosis`, `repair_task -> WorkerReply`, `review_fix -> Review`,
`review_fidelity -> Review`.

- [ ] Test rendering every operation without undefined variables, schemas in all
  structured prompts, quoted source provenance, and no full-paper/prior-code dump.
  Use the existing shared `ScriptedProvider`; add no production fake providers.
- [ ] Run prompt tests (RED). Adapt only the relevant role instructions listed in
  the design, with separate Jinja files and explicit output schemas. Keep branching
  in Python. Copy attribution/license without modifying the submodule.
- [ ] Incorporate the researched Trail of Bits property checks and K-Dense
  claim/evidence discipline into existing author/review/spec prompts. Pin source
  revisions and include applicable license notices for adapted text. Rendering
  fixtures must distinguish full-period normalization from train-only deviation,
  valid metamorphic relations from unsupported invariants, and empirical claims
  from synthetic behavior checks. No new permanent reviewer role.
- [ ] Implement packet selection and serialized UTF-8 byte checks. Test exactly
  32,768 versus 32,769 bytes, nested schema overhead, a context request for an
  unrelated path, and oversized review/fix diffs. Fresh calls carry only required
  prior failure evidence; schema repairs cannot accumulate unbounded history.
- [ ] Test bounded batch extraction/reconciliation on a synthetic long paper and
  retain every source ID through reductions. Generate `PaperSpec`/`TaskPlan`
  fragments over bounded requirement groups, assemble by controller-owned IDs,
  and review shared interfaces in pairs. Test conflicting fragment names,
  missing coverage, and a graph cycle introduced only by assembly. No call
  returns the whole accumulated plan. Keep provider/session instances
  independent across concurrent calls. Record raw invalid responses before parsing.
- [ ] Commit prompts, attribution, packet builder, and checks.

## Task 7: Make acceptance tests an independent gate

**Files:** `codes/workflow.py`, `codes/planning.py`, `tests/test_acceptance.py`.
**Consumes:** spec/interfaces, `TestSuite`, test review, Docker `ExecutionResult`.
**Produces:** `PaperCoder.prepare_acceptance(spec, plan) -> str` (frozen suite hash)
and registered `CheckSpec` records per task/integration.

- [ ] Test rejected empty/vacuous/skipped suites, unknown node targets, test-author
  context containing no candidate code, and a syntax/import setup error being
  distinguished from an expected behavior failure.
- [ ] Require property justifications, domains, numerical tolerances and oracle
  provenance in each fragment. Test that the reviewer sees sources and properties
  without candidate code. Preserve exact examples when no useful generator exists;
  unsupported properties block suite freezing even if their code executes.
- [ ] Run focused tests (RED); implement test author/reviewer steps, fixture
  staging, RED evidence against contract scaffolding, and suite freezing. Author
  per-task `TestSuite` fragments plus separate edge/end-to-end fragments; use
  disjoint acceptance directory prefixes. Test that a suite larger than one
  context window is assembled without passing the whole suite to a model.
- [ ] Ensure test files cannot supply runner config/plugins or mutate candidate
  ownership. Register required targets only after test review and collection.
  A needed test correction creates a new suite hash and invalidates old evidence.
- [ ] Run scripted flow plus real-container small acceptance tests. Assert
  `verdict=pass` cannot override failed/zero/missing test execution.
- [ ] Bind property evidence to the frozen suite and executed nodes. Classify
  generator/test defects separately from code defects; never weaken tolerances
  inside implementation repair. Calibrated reference/fault fixtures use existing
  check records; ordinary generated properties without fixtures stay explicitly
  uncalibrated. RED against a stub alone is not calibration.
- [ ] Commit acceptance preparation and its evidence gates.

## Task 8: Implement one complete task and bounded repair

**Files:** `codes/workflow.py`, `codes/execution.py`, `tests/test_task_loop.py`.
**Consumes:** accepted dependencies, task packet, frozen tests, run store.
**Produces:** `PaperCoder.execute_task(task: TaskSpec) -> TaskRecord`.

- [ ] Script cases for first-attempt success; missing context; malformed JSON;
  failed numeric test repaired once; repeated failure; API error; stale review;
  false model success; forbidden file change; and requested interface change.
- [ ] Add diagnosis cases for invalid property, inadequate generator, source
  ambiguity and infrastructure failure. Supply compact counterexample evidence;
  route test/spec corrections through review, rehash and invalidation rather than
  permitting the implementer to change its own tests.
- [ ] Run focused tests (RED); implement generate/stage/check/review/diagnose/fix/
  scoped-review transitions using the exact budgets. Generated tests/code execute
  only through Docker. Check dependency hashes immediately before acceptance.
- [ ] Preserve every candidate and raw call under unique attempt paths. Budget
  and error categories decide whether to repair, block, or cancel. A contract
  change returns a planning blocker; it is not an in-place worker modification.
- [ ] Verify exactly bounded call counts, two context expansions maximum, persisted
  counters, preserved sibling artifacts, and no exported repo on failure.
- [ ] Commit the complete single-task loop and regression tests.

## Task 9: Schedule ready tasks and integrate safely

**Files:** `codes/planning.py`, `codes/workflow.py`, `tests/test_scheduling.py`.
**Consumes:** accepted `TaskRecord`s and `execute_task` from Task 8.
**Produces:** `ready_tasks(plan, records) -> list[TaskSpec]` and
`PaperCoder.execute_plan(plan: TaskPlan) -> None`.

- [ ] Test a diamond DAG with deterministic barriers: siblings overlap, child
  cannot start before both are accepted, shared file ownership rejects the plan,
  one blocked branch does not erase an independent sibling's accepted result.
- [ ] Run tests (RED); add separate model-call and Docker semaphores. Hold the
  model semaphore only during a model call, never across a whole task/check loop.
- [ ] Publish production bundles serially; combine disjoint ownership while
  verifying consumed dependency versions. Count in-flight reservations against
  the global call cap. Invalidate changed-contract descendants and reject stale
  results returned after invalidation.
- [ ] Test concurrency maxima, cancellation while waiting/running, global budget
  exhaustion, and dependency invalidation racing with a returned candidate.
- [ ] Commit scheduling/integration and tests.

## Task 10: Wire CLI, resume, final checks, and reports

**Files:** `codes/workflow.py`, `codes/store.py`, `README.md`, scripts,
`assets/workflow.tex`, `assets/workflow.svg`, `tests/test_workflow.py`,
`tests/test_resume.py`.
**Consumes:** all prior components. **Produces:** the CLI documented in execution
spec, a complete `RunReport`, and export only from an integration-verified snapshot.

- [ ] Test OpenRouter model inference including the exact `:nitro` suffix, early
  rejection of host CLI aliases, role overrides, unused output paths, invalid
  resume overrides, Docker preflight,
  and all-template rendering before the first paid call.
- [ ] Run focused tests (RED); make `run()` orchestrate source/spec/plan/acceptance/
  execution/integration/fidelity/report phases. Keep model construction at CLI
  boundary and `TEMPLATE_ROOT` initialization once before concurrent work.
- [ ] Add durable resume, final checks, hashed report provenance, readable progress,
  budget summaries, and explicit unknown token/cost fields. Exit nonzero for
  incomplete work; return 130 for SIGINT after Docker cleanup.
- [ ] Report source -> requirement -> property -> node -> execution links,
  calibration status and explicitly deferred empirical claims. Tested code may
  export without claiming published-result reproduction; unresolved required
  method behavior still blocks acceptance.
- [ ] Run no-paid-call end-to-end and interrupt/resume checks. Confirm completed
  tasks are reused, changed inputs rejected, integration regressions reopen owning
  tasks/descendants, and final export matches the accepted snapshot.
- [ ] Update CLI examples (including `pipefail` with `tee`), README, and TikZ/SVG.
  Commit after all application and required Docker checks pass.

## Task 11: Run the small-model evaluation ladder

**Files:** `eval/run.py`, `eval/fixtures/`, `eval/acceptance/`,
`tests/test_eval.py`, experiment artifacts under unused `outputs/` paths.
**Consumes:** final CLI, frozen baseline, model ID and stage budgets from design.
**Produces:** reproducible run manifests and evidence reports; no fabricated result
or large-model-equivalence claim.

- [ ] Create a small numerical-method fixture with two independent tasks and an
  integrating task. Write external acceptance tests and deliberately incorrect
  examples proving the tests catch the target bugs; keep these outside model
  mutation and do not tune them after seeing candidate outcomes.
- [ ] Calibrate at most six independently adjudicated reference/fault pairs
  (12 Docker checks) within existing time limits, plus valid/invalid/ambiguous
  property-review cases within model call limits. Include constant-output false
  positives, annualization conventions and full-period versus train-only scaling.
  Count semantic assertion failures only; report inconclusive controls. Measure
  false acceptance/rejection and unresolved judgments with denominators.
- [ ] Freeze holdout checks separately from visible development fixtures. Never
  feed holdout content into model repair; if revealed, relabel it development
  evidence. Do not claim reviewer independence or equivalence from one micro-run.
- [ ] Test the evaluation driver offline, including failed/cancelled runs, unknown
  cost, baseline provenance, and inclusion of all repair calls in totals.
- [ ] After implementation approval and offline/Docker success, run the exact
  GPT OSS Nitro micro-stage (30 calls/15 minutes), then the AlphaEvolve component
  stage (60 calls/30 minutes). Verify availability at paid preflight; preserve
  failure evidence if provider access or structured responses fail.
- [ ] Only after those pass, run full bounded generation (120 calls/60 minutes)
  and CPU synthetic smoke. No paid calls or images are launched while merely
  preparing this plan. Do not use the exposed old API key.
- [ ] Report observed correctness, fidelity, cost availability, and wall time.
  Commit fixtures/driver/docs; retain run logs in ignored artifacts. Prepare the
  later repeated small/large × old/new comparison without selecting a stronger
  model or spending its budget silently.

## Final review and acceptance

Before execution, resolve any design amendment in the spec first and update the
affected task. After implementation, run application regression tests, required
Docker integration tests, and the staged model evaluation separately; report
their outcomes separately. Review the complete change against the five Review
Focus items and the source-grounded acceptance criteria.

Planning completion means the branch and these documents exist and have been
checked for consistency. It does not mean any proposed tool, Pydantic model,
Docker isolation, resume feature, or model experiment has been implemented.

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
