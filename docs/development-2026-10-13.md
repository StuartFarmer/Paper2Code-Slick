# Development record — improved workflow

Implemented on `improved`; the paid evaluation ladder is still pending.

## Verification

Final suite: **109 passed**, including **13 real Docker checks**. Ruff and
whitespace checks passed. Native-Linux permissions were verified structurally;
the actual Docker executions used Docker Desktop on Apple Silicon.

- Scripted-provider end-to-end run executed generated code in real Docker.
- Three numerical reference/fault pairs: 3 references passed, 3 faults rejected.
- No paid model calls: OPENROUTER_API_KEY was absent.
- Prompt and diagram assets are updated; the TikZ source compiles to the SVG.
- User-staged submodules and unrelated local files remain untouched.

## Review

A fresh reviewer found five important issues. Each had a failing reproduction
before its fix: cancellation while removing a container, generated import defects
bypassing repair, source bytes omitted from batch sizing, extracted unresolved
references dropped from reports, and private snapshot permissions. All were fixed
in one pass. No minor findings were deferred. Deliberately adversarial runner
forgery, paid model performance, and documented unsupported V1 cases were outside
the review's evidence; the decisions below retain those limits explicitly.

## Scope decisions and development ledger

The ledger is retained verbatim below so plan amendments and costs are visible.
The original checklist remains aspirational where an implementation amendment
narrows it; this record does not mark every original plan test or evaluation complete.

# SDD ledger — plan: docs/superpowers/plans/2026-10-13-improved-workflow.md

Baseline: fb8e02f on improved; 34 application tests pass with explicit `tests/`.
User's pre-existing staged submodules and unstaged runtime/docs edits preserved.

Ruling: work in the requested improved branch in this checkout; preserve a frozen
baseline before editing runtime. A second worktree would omit the approved dirty
runtime/research state; risk is shared working-directory changes, mitigated by
explicit file ownership and exact-path commits.
Ruling: restrict pytest discovery to tests/ after the unscoped baseline command
attempted to collect outputs/ generated tests. Generated checks belong in Docker;
omitted output tests are intentional, not application regressions.

Preflight dependency scan:
- Tasks 1 -> 11: frozen dirty-source manifest feeds baseline comparison; consistent.
- Tasks 2 -> 3/4/5/6/7: model IDs/path rules shared; implement once in planning.
- Tasks 3/4 -> 6: indexed source and immutable artifacts feed bounded packets.
- Tasks 5/6 -> 7/8: checks return controller evidence; prompts never fabricate it.
- Tasks 7/8 -> 9/10: immutable suite and accepted hashes gate dispatch/export.
- Tasks 10 -> 11: offline and Docker success precede paid evaluation.
- Research amendment: PropertySpec links and empirical deferral must survive every
  stage; no GEPA or stronger-model fallback in V1.

Task 1: in progress.

Task 4: Ruling: unclean crash downtime is conservatively charged as active time;
only cleanly closed pauses are excluded. Exact crash duration is unknowable
without an external observer. Cost: a long unclean pause can exhaust the run.

Task 6: Ruling: develop the new owning PaperCoder in codes/agent.py and keep
codes/workflow.py as the eventual CLI/re-export. This avoids replacing the working
CLI before the task loop is verified. Cost: one extra module boundary; no second
maintained runtime after cutover. Common path confinement moves to codes/paths.py
to avoid circular imports among the controller, storage, planner and executor.
Task 1: complete (commits fb8e02f..936e909, tests: .venv/bin/python -m pytest -q → 36 passed in 0.42s)
Task 2: complete (commits 936e909..0a49a09, tests: .venv/bin/python -m pytest -q → 58 passed in 0.47s)
Task 3: complete (commits 0a49a09..04cd547, tests: .venv/bin/python -m pytest -q → 67 passed in 0.46s)
Task 4: complete (commits 04cd547..f06b9e7, tests: .venv/bin/python -m pytest -q → 72 passed in 0.49s)
Task 5: complete (commits f06b9e7..24b12af, tests: env P2C_TEST_IMAGE=sha256:e6f67d91791e3b97bb82c48db6c1e01ce93b97eac869d467720fabef114ba5f4 .venv/bin/python -m pytest -q → 93 passed in 16.00s)

Task 5: Ruling: pin a verified CPython 3.11 Linux ARM64 CPU Torch wheel; the generic
index resolved an unavailable release. Cost: x86 requires a separate verified lock.
Task 6: Ruling: keep exception handling in run_verified outside @workflow because
Slick 0.4 rejects Try syntax. Cost: Python API callers should use run_verified.
Tasks 6-10: Ruling: complete the shared owner/CLI cutover together after testing
individual boundaries; one combined commit avoids publishing a half-wired runtime.
Cost: a larger reviewable commit than the plan's proposed per-phase commits.
Task 6: Ruling: oversized interface registries/indivisible packets block with a
byte-budget error; automatic pairwise registry repartition is deferred. No evidence
is silently dropped. Cost: large papers may need narrower consolidated inputs.
Tasks 7-8: Ruling: test/spec/contract corrections block and require a new run;
implementation repairs remain automatic and bounded. Cost: rejected scientific
assumptions need intervention; this prevents a worker weakening its own tests.
Task 11: Ruling: component/full stage reports rely on generated acceptance, with
external paper-specific adjudication explicitly manual. Cost: procedural success
cannot be treated as paper-result reproduction or model equivalence.

Tasks 6-10 implemented: typed prompts/packets, frozen independent tests, task loop,
DAG scheduling, CLI, resume, reports, docs and diagram. RED/GREEN checks include
vacuous scaffold tests, malformed responses, provider failures, context limits,
immutable artifact recovery, atomic snapshots and real Docker import collisions.
Task 11 implemented offline driver, three reference/fault pairs, external micro
checks and property-review cases. Six real Docker controls: 3/3 reference pass,
3/3 faults rejected, no inconclusive checks. Human adjudication pending.
Paid stages blocked: OPENROUTER_API_KEY is absent; no model calls or equivalence
claims made. Existing exposed key is not reused.

Pre-review validation: 103/103 application + real Docker checks passed; Ruff and git diff --check passed. TikZ compiled to SVG. Paid trials remain blocked, not marked complete.

Final fresh review: five Important findings, no Critical or Minor findings.
RED reproductions observed for all five; one fix pass applied:
- cancellation during removal: explicit cleanup task awaited before cancellation propagates;
- import defects: generated import errors are repairable failures, runner/test setup errors remain infrastructure;
- multipart context: partition using fully rendered operation packets, including source and schema;
- missing method references: preserve extraction warnings in source/unresolved.json and report, block before planning;
- POSIX permissions: published snapshot dirs 0755/files 0644 even under umask 077.

Final: Ruling: deliberately adversarial in-process result fabrication remains outside
V1's anti-cheating guarantee, as specified; Docker isolates the host. Cost: passing
checks are evidence for ordinary generated code, not adversarial proof.
Final: Ruling: paid model performance/scientific adjudication/equivalence remain
unjudged because no trial credentials or independent adjudication are available.
Cost: no evidence yet that GPT-OSS completes a real-paper run or matches larger models.
Final: Ruling: retain documented x86, oversized-registry and automatic test/spec
correction limits; source-aware batching now handles divisible ordinary packets.
Cost: those unsupported cases require a new lock, narrower input, or a corrected run.
Final: Ruling: extracted unresolved method references block instead of allowing an
unreviewed guess. Cost: false-positive extraction warnings require clarified source.
No deferred minor findings.

Final: fixed all five Important findings — individual reproductions RED→GREEN;
full application + real Docker suite 109/109 passed in 20.64s. Ruff and whitespace
checks pass. No runtime changes after that verification. Final diagram regenerated.
Task 11 paid evaluations remain blocked; keep workspace/ledger for continuation.
