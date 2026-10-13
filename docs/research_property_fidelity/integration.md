# Blending scientific fidelity with property testing

Date: 2026-10-13. Status: researched V1 design amendment on `improved`, not
implemented or experimentally validated. GEPA is reserved for V2.

## Decision

Make the existing independent test-author/reviewer steps produce and assess a
traceable argument: **source -> requirement -> justified property -> test ->
measured result**. Property testing explores whether code obeys the relationship;
scientific review asks whether that relationship is warranted at all. Neither
alone establishes reproduction. Keep Slick orchestration, short packets, Docker,
immutable acceptance tests and bounded repair; add no agent framework.

The current runtime still plans, analyzes and writes files. These changes amend
the proposed improved workflow, not its current execution behavior. Detailed
source research is in [property-testing findings](findings_property_testing.md)
and [scientific-fidelity findings](findings_scientific_fidelity.md).

## What to adapt from the skills

| Source | Adopt in our prompts | Do not adopt wholesale |
| --- | --- | --- |
| [Trail of Bits property testing](https://github.com/trailofbits/skills/blob/main/plugins/property-based-testing/skills/property-based-testing/SKILL.md) | Identify meaningful invariants/oracles, construct valid generators, ask which wrong program could pass | A universal ranking of property strength, security-specific workflow, or inaccurate claims that exhausted assumptions pass |
| [K-Dense scientific critical thinking](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-critical-thinking/SKILL.md) | Fix claim scope and conditions, extract evidence first, distinguish missing reporting from demonstrated failure | General manuscript-review ceremony or treating a checklist as validation |
| [K-Dense peer review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md) | Claim/evidence alignment, explicit uncertainty, reproducibility evidence | A separate review platform or declared support without observed results |

These are prompt sources, not evidence that our small model will improve. Pin
upstream revisions/content hashes and retain the applicable licenses/attribution
when adapting text during implementation; no installed skill discovery at runtime.
The local paper-code-audit prompt offers a compatible claim/code/defaults audit.

## Handoffs within the existing workflow

1. **Extract and reconcile:** retain `Requirement.basis`; add `claim_kind`
   (`method`, `mathematical`, `empirical`) and frozen `verification_scope`.
   Method ambiguities block affected work. Missing empirical data may be deferred
   with a reason; synthetic tests cannot discharge that claim. Keep the existing
   deviations list rather than introducing a separate issue system.
2. **Author tests:** return `TestSuite.properties` alongside executable files.
   Each `PropertySpec` names requirements, domain/preconditions, relation,
   justification, oracle provenance, numerical tolerance and pytest node IDs.
   Use exact examples when stronger or simpler than generated cases. The author
   receives cited excerpts and interfaces, never candidate code.
3. **Review tests:** reuse `review_tests`, in a fresh bounded context, to assess
   source entailment and test quality together. Require valid transformed inputs,
   meaningful nonconstant examples, independently justified expectations, and
   explicit exclusions. A quote match only proves the quoted text exists.
4. **Freeze and execute:** Python resolves IDs and registers checks; Docker
   supplies results. Preserve existing RED evidence, but a stub failing is not
   proof a scientific assertion detects the intended error. Calibration fixtures
   supply that additional evidence for selected high-risk behaviors.
5. **Repair:** pass only the requirement/property, relevant code, failed node,
   counterexample and measured result. Classify implementation defect, bad
   property/generator, source ambiguity or infrastructure failure before routing
   repair. Changing a test/tolerance requires separate review, a new suite hash
   and invalidation; a worker cannot weaken its own acceptance criteria.
6. **Report:** show source and engineering deviations, properties checked on their
   declared domains, matching execution evidence, and deferred empirical claims.
   Passing finite examples does not prove a theorem or reproduce reported scores.

Property packets and their schemas count toward the existing 32,768-byte limit.
Task-level authors/reviewers can run in parallel; shared-interface tests wait
for both contracts. No new always-on reviewer role or hidden call budget is
needed. Same-model fresh contexts give procedural separation, not proven
independence of errors.

## Concrete AlphaEvolve cases

The local source is `/Users/stuart/Developer/AI/arXiv-2103.16196v2/paper/main.tex`;
the run will snapshot it and assign stable source IDs rather than depend on this
machine path. These examples inform the initial external evaluation fixtures.

| Claim or choice | Suitable checks | Fidelity trap |
| --- | --- | --- |
| Per-stock feature maximum across all time steps (`main.tex:301`) | Small exact fixture using the full-period maximum; positive rescaling invariance only on its valid domain | Train-only normalization contradicts the stated procedure. It is a separately recorded engineering deviation, not a paper requirement. |
| Train-only scaling, if deliberately selected | Changing held-out extremes leaves fitted scales unchanged, plus a hand-calculated nonconstant training fixture | An always-zero implementation passes the invariance alone. Never enforce this alongside the incompatible full-period contract. |
| Sharpe annualized over 252 days (`main.tex:342`) | Exact daily-return fixture and scaling check; explicitly choose daily arithmetic mean ×252 and daily SD ×sqrt(252), risk-free zero, SD convention and zero-variance policy | The passage does not settle every convention. Mark the conversion/SD choices and their rationale; multiplying both quantities by sqrt(252) cancels annualization under this chosen contract. |
| Causal time interface, if established | Appending future observations leaves historical outputs unchanged | Shuffling time order is not a valid general invariant; centered or full-sample operations need different contracts. |
| Reported investment performance | Record required dataset, split, metric, baseline, seeds/repetitions and uncertainty | CPU synthetic smoke cannot confirm the published performance. |

For literal replication, retain the paper's full-period normalization and flag
its methodological limitation. For the proposed causal-preprocessing component
exercise, declare the train-only deviation before generation. This is a frozen
spec decision, not a new general-purpose CLI mode or a silent repair.

## Executor addition

Add pinned Hypothesis to the planned executor lock. Use the existing registered
pytest checks and Docker limits; no new runner or mutation dependency. Proposed
starting profile: `max_examples=100`, `derandomize=True`, `database=None`,
`deadline=None`, `print_blob=True`, explicit/generate/shrink phases and no health
check suppression. The trusted runner loads it before test imports, keeps pytest
plugin autoload disabled and explicitly loads the pinned Hypothesis plugin.

Review/reject unapproved per-test settings overrides. Bound shapes and magnitudes,
construct valid inputs directly, reset state per generated case, and record RNG
choices. Specify dtype, finite/nonfinite policy, exact shapes and absolute/relative
tolerances with reasons. Do not silently widen tolerances after failure.

`max_examples` is not a process execution cap; the existing container deadline
bounds filtering and shrinking. Record valid/invalid cases and stopping reason
where exposed, plus minimal failing inputs/replay text inside bounded logs.
Health-check, unsatisfiable and flaky failures require diagnosis; they are not
scientific passes. Replay depends on frozen test, Python, Hypothesis and other
environment versions. Truncated replay evidence is explicitly incomplete.
[Hypothesis settings](https://hypothesis.readthedocs.io/en/latest/reference/api.html),
[case-count semantics](https://hypothesis.readthedocs.io/en/latest/explanation/test-case-count.html),
[replay](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html).

## First evaluation and success criteria

Use the existing micro/component ladder with GPT OSS 120B Nitro. Before paid
calls, build a small independently adjudicated fixture set containing correct
implementations, specific semantic faults, invalid properties and ambiguous
source passages. For selected critical behaviors, pair a correct reference with
one intentional fault; cap initial calibration at six reference/fault pairs
(12 check launches total), all inside existing active-time limits. This cap is
an engineering starting point, not a research result. Calibration runs inside
Docker; missing dependencies, crashes and timeouts are inconclusive controls.

Only count a fault detected when the relevant assertion fails for the expected
semantic reason and the reference passes. Record detected/eligible counts and
exclusions. Do not require a blanket mutation score or build an automated mutation
campaign. Generic papers without independent fixtures receive explicitly
uncalibrated test evidence; do not manufacture trusted references with the same
model and call them ground truth.

For the reviewer, measure invalid properties incorrectly accepted, valid
properties incorrectly rejected, and genuine ambiguities left unresolved. For
the code, measure acceptance of known-good examples and rejection of known faults.
Report each denominator, all calls, fixes, cost availability and wall time.
Freeze separate holdout fixtures before model trials. Keep their contents out of
prompts/repair; a revealed holdout becomes development evidence and requires a
fresh holdout for an unbiased final assessment.

First demonstrate this combined flow works; a later controlled comparison can
separate the contribution of property tests from fidelity review. Do not claim
superiority or large-model equivalence from one successful smoke run.

## V2: GEPA boundary

V1 saves versioned prompts, typed outputs, domain-specific failure feedback and
measured trajectories. That provides useful material for the user's later GEPA
investigation. V1 does not add an optimizer or tune against final evaluation
fixtures. V2 will need its own training/validation/held-out split, objective,
compute budget and assessment of reward gaming. Those choices remain research
work, not hidden scope in this implementation plan.
