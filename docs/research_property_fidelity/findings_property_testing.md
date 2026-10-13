# Property-based and metamorphic testing findings

Research date: 2026-10-13. Scope: proposed V1; no implementation, package
installation, container execution, or performance measurement. Two web search
queries were used; other sources were opened directly. Recommendations below are
proposed engineering choices, not findings of improved scientific fidelity.

## Evidence and its limits

The [Trail of Bits skill](https://raw.githubusercontent.com/trailofbits/skills/main/plugins/property-based-testing/skills/property-based-testing/SKILL.md)
recommends properties when a meaningful inverse, invariant, or oracle exists,
with examples including roundtrips, idempotence, and independent references.
Its central review question is whether a plausible broken implementation could
falsify the assertion. A repeated call can test determinism; comparing a saved
result with itself cannot. The skill explicitly excludes mutation campaigns
from its scope. It is useful prompt guidance, not evidence that adding it improves
Paper2Code. Its suggested property-strength ordering is a heuristic: a roundtrip
can conceal paired bugs and does not universally dominate a scientific invariant.

The [generation guidance](https://raw.githubusercontent.com/trailofbits/skills/main/plugins/property-based-testing/skills/property-based-testing/references/generating.md)
favors generating valid inputs directly, deriving dependent values together,
and explicitly including known boundaries. The
[review guidance](https://raw.githubusercontent.com/trailofbits/skills/main/plugins/property-based-testing/skills/property-based-testing/references/reviewing.md)
flags implementation-shaped expected results, excessive filtering, missing
assertions, and weak assertions. Do not copy its claim that contradictory
assumptions merely pass or surface as an ignored warning: Hypothesis defines
`Unsatisfiable` and `FailedHealthCheck` exceptions for these problems. Preserve
those failures as evidence of defective tests, not scientific failures or passes.
[Hypothesis exception definitions](https://hypothesis.readthedocs.io/en/latest/_modules/hypothesis/errors.html)

Hypothesis float strategies may include NaNs, infinities, and subnormal numbers
unless excluded. Width selects representability; `width=32` still yields Python
float objects. Bounds and excluded endpoints define the domain, while shrinking
seeks simpler counterexamples rather than representative samples.
[Strategies reference](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html#hypothesis.strategies.floats)
Python's `math.isclose` combines absolute and relative tolerances; a positive
absolute tolerance is needed for useful comparisons near zero. NaNs are never
close and matching infinities are close.
[Python numerical comparison](https://docs.python.org/3/library/math.html#math.isclose)

Hypothesis documents `derandomize=True` as reproducible until the test, Python,
or Hypothesis changes. A seed does not remove external nondeterminism. Settings
can be overridden on individual tests. Its deadline applies to individual cases
and is soft in some circumstances, rather than a process watchdog. Explicit
examples do not count toward `max_examples` and do not shrink. Pytest
function-scoped fixtures reset once per test function, not once per generated
input. [API reference](https://hypothesis.readthedocs.io/en/latest/reference/api.html)
Filtering, shrinking, and failure confirmation can add executions beyond
`max_examples`; exhaustion of a finite domain can legitimately produce fewer.
[Test-case counts](https://hypothesis.readthedocs.io/en/latest/explanation/test-case-count.html)

Failures can be retained as explicit examples or temporary reproduction blobs;
blobs require the same Hypothesis version. The default example database is local
state; disabling it is supported.
[Replay documentation](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html)
Unmanaged randomness and state surviving between cases cause flaky failures and
can prevent reliable shrinking. [Flaky failures](https://hypothesis.readthedocs.io/en/latest/tutorial/flaky.html)

## Proposed property contract and authoring rules

Extend the existing acceptance contract, rather than introduce another agent or
workflow. Store a small property record with `id`, `requirement_ids`, `basis`,
source references/rationale, `kind`, domain/preconditions, assertion or relation,
reference-oracle provenance if applicable, tolerance policy, and test node IDs.
An explicit-example check can use the same record without a generator. Keep
scientific assumptions separate from executable domain restrictions.

For every generated property, require the author and fresh reviewer to answer:

1. What source-supported behavior does it constrain, and under what conditions?
2. What valid inputs and boundaries reach the assertion? Are the original and
   transformed inputs both valid, and does the transformation actually change
   the relevant data?
3. Which plausible defect should fail, and which wrong implementations could
   still pass? How does a separate example or oracle cover that weakness?
4. Does the expected result come from independently justified reasoning, or
   simply copy production logic?

Do not require a property for every requirement. An exact, hand-calculated
fixture can be stronger than an invented invariant. Examples for the planned
training-scale task are proposals pending source adjudication:

| Candidate check | Useful constraint | Necessary companion / limitation |
| --- | --- | --- |
| Change held-out extremes with training fixed | Fitted training scales remain unchanged | A constant-output implementation also passes; add a hand-calculated nonconstant training fixture. |
| Append later observations while holding a historical prefix fixed | Earlier causal outputs remain unchanged | Only valid for the stated causal interface; centered windows or full-sample estimates need different contracts. |
| Permute feature columns and corresponding labels together | Output follows the same permutation | Only when feature-specific parameters are transformed too and the method supports this symmetry. |
| Roundtrip a serialized parameter object | State survives storage | Pair with expected field semantics; matching encoder/decoder bugs can cancel. |

Never infer permutation invariance for time order, associativity for floating
arithmetic, monotonicity for arbitrary objectives, or deterministic training from
method names alone. Passing necessary conditions is not proof of the algorithm.

For numerical properties, specify shapes, dtype, magnitude bounds, missing and
nonfinite policy, zero/degenerate cases, and valid transformation parameters.
Use small constructive strategies and explicit boundary examples. Include
nonfinite rejection separately when the public interface promises it; restricting
a finite-only generator must not silently weaken that promise. Check shape and
finiteness before closeness so broadcasting or matching infinities cannot conceal
errors. Choose and justify absolute/relative tolerance per operation, dtype,
scale, and reference error; no universal epsilon and no widening after seeing a
candidate fail without a separately reviewed suite revision. Exact identities
remain exact where the contract supports them.

## Proposed Docker and replay integration

The current execution proposal already has the right external controls: fixed
registered checks, read-only inputs, no network, 1 CPU, 2 GiB memory, and 120-second
check deadlines. Keep them; do not add a host execution path. Add Hypothesis only
to the explicitly approved executor lock during implementation, pinning the
validated version. No runtime installs or automatic dependency resolution.

Use a trusted runner-owned profile before importing tests: `max_examples=100`,
`derandomize=True`, `database=None`, `deadline=None`, `print_blob=True`, no health
check suppression, and explicit/generate/shrink phases. These are starting
engineering defaults requiring later runtime calibration, not universal safe
limits. Require review of per-test decorators that override them. Bound array
sizes and operation counts, keep training to smoke tests, and let the existing
container deadline bound hangs and shrinking. A timeout is incomplete execution,
not a passing property or proof of a scientific error. Do not expand existing
run budgets to compensate automatically.

Keep `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, but explicitly allowlist Hypothesis's
pytest plugin (`-p hypothesispytest`, checked against the pinned image) and the
trusted result plugin. Hypothesis's plugin provides statistics and profile/seed
options; pytest permits explicit plugin loading with autoload disabled.
[Hypothesis integration](https://hypothesis.readthedocs.io/en/latest/reference/integrations.html#the-hypothesis-pytest-plugin),
[pytest plugin controls](https://docs.pytest.org/en/stable/how-to/plugins.html#disabling-plugins-from-autoloading)

Capture valid/invalid cases, stop reason, health-check/flakiness outcomes, and
replay evidence alongside existing candidate/dependency/suite/image hashes.
Missing statistics are unknown, not zero or success; small exhausted domains are
acceptable when justified. A collected pytest node alone does not establish
meaningful generated coverage. Keep mandatory boundaries as explicit examples;
use statistics to diagnose diversity, not as a statistical coverage guarantee.
Reset mutable state inside every case and control each numerical library's RNG
where needed; record Python/dependency versions, architecture, profile and seeds.

Keep reproduction text within existing bounded logs. Prefer a small explicit
regression input after adjudication; temporary blobs help same-version debugging.
Do not mount a writable persistent Hypothesis database from the host. If output
truncates a counterexample, mark replay evidence incomplete; any focused rerun
uses existing check/time budgets. Adding a regression example changes the frozen
suite hash and invalidates affected acceptance evidence under existing rules.

## Proposed bounded mutation calibration

Use a few reviewed negative controls in curated development fixtures, not an
open-ended mutation service or a new mutation dependency. For each high-value
property, associate a concrete intended defect, such as fitting on held-out data,
shifting a causal window by one period, changing a required denominator, ignoring
a nonconstant input, or breaking zero-scale behavior. Only choose defects that
violate an adjudicated requirement on the registered domain.

Run the correct small reference/fixture first, then each separately frozen
mutation in the same Docker limits and against the same approved suite. Count a
kill only when a relevant scientific assertion fails; syntax/import errors,
infrastructure failures, OOMs and timeouts are invalid/inconclusive controls.
Report equivalent or out-of-domain mutations separately. A surviving mutation
may expose a weak property or an invalid control; investigate before changing
requirements or tolerances. Missing implementation RED evidence is not semantic
calibration. A reference that fails its own suite blocks calibration.

Suggested initial cap: one or two intentional mutations per selected critical
property, with an explicit total calibration cap inside the existing run/check
budget. This is a proposed workload cap, not an empirically chosen threshold.
Avoid a universal mutation-score acceptance target. Keep independently curated
holdout acceptance tests separate from test-author prompts and repair feedback
when evaluating the overall workflow; otherwise mutation tuning can overfit the
visible suite. Report detected/eligible controls and exclusions, not a claim of
measured improvement or full scientific fidelity.
