# Evaluation evidence

`fixtures/micro.md` specifies two independent numerical modules and their integrating
consumer. `acceptance/holdout` is frozen before generation and never sent to model
repair. Reading or revealing those tests to a model makes that run development
rather than held-out evidence. These fixtures were authored during implementation;
no independent human adjudication has occurred yet.

`calibrate` runs three correct/fault pairs in Docker. Only semantic assertion failures
count as rejection; infrastructure errors are inconclusive. The controls establish
these particular test/bug relationships, not calibration of future generated tests.
`fixtures/property_cases.json` provides five valid/invalid/ambiguous judgments for
future blinded property-review evaluation. Expected labels still need human review;
no model-review accuracy measurement is claimed.

The full-period scaling control distinguishes a literal all-time-extrema contract
from train-only fitting. It does not claim min-max is every paper's normalization
formula. AlphaEvolve's all-time normalization statement must be checked against its
actual formula and source spans before transferring this control.

The pre-change runtime was frozen locally at
`outputs/baselines/pre-improved-2026-10-13/`, including the experimental JSON healer.
Its manifest hashes the dirty source actually used, rather than pretending HEAD
alone identifies it. Pass `--baseline path/to/manifest.json` to bind a trial to that
baseline. This directory is ignored and is not distributed with the repository.

Current component/full evaluation uses generated tests plus fidelity review. There
is no external paper-specific empirical oracle yet; promotion is procedural evidence,
not published-result reproduction. A genuine small/large × old/new comparison needs
repeated trials, fixed external checks and independently adjudicated outcomes. No
stronger model is selected automatically. GEPA belongs to V2.
