# Scientific fidelity and property acceptance: findings

Research date: 2026-10-13. Design research only; five web searches, primary sources.
Read the research plan and current improved-workflow design/contracts. No code,
container, installation, or paid evaluation was run. GEPA remains V2 only.

The missing connection is a reviewable derivation from a cited claim to a bounded
property, then to measured execution evidence. The current design already has
independent test authoring, source spans, immutable suites and execution hashes;
extend those records rather than adding a new agent framework.

## What the primary sources establish

- **K-Dense scientific-critical-thinking**, current upstream `skills/` path,
  version 1.5: fix the claim, comparison, timing and sampling unit before appraisal;
  extract evidence before judgment; distinguish missing reporting from evidence
  a procedure was omitted. It separates reporting completeness, bias, and evidence
  certainty, and asks for source location, consequence, uncertainty and remedy.
  These are procedural instructions, not measured proof of reviewer accuracy.
  [Source](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-critical-thinking/SKILL.md).
- **K-Dense peer-review**, version 2.4: its claim matrix links claim IDs and
  locations to evidence, support, alignment limitations and requested action.
  Reproduction must not be claimed without actual inputs, commands, environment
  and outputs. Its explicit distinction between incomplete reporting and invalid
  methods is useful here. Formal confidential-manuscript intake is outside this
  public-source code-generation task.
  [Source](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md).
  The actual validator rejects a declared supported claim without evidence IDs,
  but does not resolve their truth: it explicitly checks declared structure only.
  Do not copy this as an evidence-verification engine.
  [Validator](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/scripts/validate_claim_evidence.py).
- **Chen, Cheung and Yiu, HKUST-CS98-01**: metamorphic testing derives additional
  cases from successful cases to reveal otherwise missed errors where ordinary
  output oracles are unavailable. This supports complementary checks, not proof
  of correctness. The repository's 2020 arXiv upload identifies the original
  technical report; only its readable abstract/metadata support this summary
  because PDF text extraction was corrupted.
  [Original report record](https://arxiv.org/abs/2002.12543).
- **Lin, Simon and Niu, exploratory scientific MT**: their SWMM integration study
  examines competing outcome patterns rather than assuming each optimization
  iteration improves fit. It distinguishes bugs, integration mismatches, and
  constraints. A surprising relationship can therefore motivate diagnosis without
  already being a valid acceptance failure.
  [Author manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC7252536/).
- **Pineau et al., JMLR 2021**: missing data, unspecified training/metrics,
  selective reporting and overclaiming undermine reproducibility; published code
  can reproduce mistakes. Their program evaluates code submission, a reproduction
  challenge and a checklist, but explicitly does not establish that these measures
  improve scientific quality. Record actual data/tools used and the precise claim
  assessed rather than relying on a generic reproduced label.
  [Paper, sections 1, 2.1, 3 and 6](https://jmlr.org/papers/volume22/20-303/20-303.pdf).
- **Zheng et al., NeurIPS 2023**: LLM judges show position, verbosity,
  self-enhancement and reasoning limitations in conversational preference
  evaluation. That study does not validate scientific code review or GPT OSS.
  It motivates measuring our reviewers rather than treating fresh contexts as
  demonstrated independent correctness.
  [Paper record](https://proceedings.neurips.cc/paper_files/paper/2023/hash/91f18a1287b398d378ef22505bf41832-Abstract-Datasets_and_Benchmarks.html).

Upstream skill versions were read from `main`; these URLs are mutable. Pin the
exact fetched revision/content hash before copying prompt material. Source popularity
and claims of validation were not used as evidence.

## Proposed V1 adaptation: one traceability chain

These are project recommendations, not behavior already implemented upstream.

Use `Requirement` as the claim identity; avoid a parallel claim database. Preserve
its `basis`, source spans and rationale. Add `claim_kind` with
`method | mathematical | empirical`, and `verification_scope` with
`v1_required | deferred_empirical`. The latter is frozen in planning, cannot be
changed by a candidate or reviewer, and needs a reason for deferral. Engineering
choices still use the existing `basis` field; claim kind must not overwrite it.

Add one `PropertySpec` list to `TestSuite`:

| Field | Meaning |
| --- | --- |
| `id`, `requirement_ids`, `node_ids` | Stable property, source requirements and actual pytest targets |
| `kind` | `example | invariant | metamorphic | differential` |
| `justification` | Why this necessary relationship follows from the cited method or declared engineering choice |
| `domain_and_preconditions` | Shapes, units, ranges, ordering, conditioning and exclusions |
| `relation` | Inputs/transformation and asserted output relationship |
| `oracle_basis` | `hand_derived | independent_reference | necessary_relation` |
| `oracle_evidence` | Derivation, versioned reference artifact, or reasoning independent of candidate implementation |
| `tolerance` | Exact comparison or explicit numerical/statistical tolerance and rationale |

Reuse `SourceRef` through requirements instead of duplicating quotes. A property
may reference an additional definition requirement when derivation spans sections.
The graph is `source span -> requirement -> property -> pytest node -> execution
artifact`, with review findings attached at any failed edge. Quote matching proves
text presence; the reviewer must still check entailment and omitted conditions.

Replace free-text `PaperSpec.deviations` with a small structured record:
`requirement_ids`, `kind: ambiguity | missing_input | deviation`, `description`,
`needed_evidence`, `disposition: blocks_v1 | deferred_empirical`, `rationale`.
No separate agent or approval queue. Existing bounded reconciliation resolves
issues; material algorithm ambiguity blocks affected tasks. A missing research
dataset may defer empirical reproduction while leaving synthetic implementation
checks feasible. A documented shortcut does not satisfy the original requirement.

Extend `Finding` only with `property_ids` and `evidence_artifact_ids`, allowing
concrete counterexamples and faulty assumptions to use the current review/repair
loop. The final controller report derives coverage per requirement; an LLM's
supported label never substitutes for matching execution records.

## What review and gates must establish

1. **Before freezing tests:** the scientific reviewer checks each property's
   derivation, hidden assumptions and domain. Numerical equality over real numbers
   does not imply exact floating-point equality. Permuting independent observations
   may preserve a statistic; shuffling time-series observations can destroy the
   model's intended information. Improved predictive performance is an empirical
   claim, not a universal metamorphic law. Unsupported candidate relations remain
   exploratory notes and cannot gate code acceptance.
2. **Oracle independence:** the author sees sources/contracts but no candidate.
   A reference calculation must not call the production helper it is checking.
   Cross-check selected fixtures by a hand derivation or independently structured
   computation. Metamorphic consistency alone can admit an always-zero program;
   combine it with a nonzero anchor/example that distinguishes correct output.
   Same-model fresh contexts provide process separation, not proven statistical
   independence; retain the curated external fixtures already planned.
3. **Controller checks:** resolve all property/requirement/node IDs; require each
   V1 binding requirement to have applicable evidence, not merely a test in its
   owning task. Check nonempty domains, explicit tolerance, available oracles,
   and no unresolved blocking issue. Review semantics remain fallible; Python
   enforces referential integrity and measured outcomes. Test execution must
   exercise the property without skip, xfail, empty collection or vacuous input
   filtering. Preserve candidate/dependency/suite/image hash gates.
4. **Counterexample handling:** distinguish implementation defect, incorrect
   property, inadequate generator, ambiguous source and infrastructure failure.
   Shrinking identifies a small failing case, not which side is wrong. Test/spec
   corrections use the existing independent review, new hashes and invalidation;
   never weaken a tolerance solely to make a candidate pass.
5. **Separate outcomes:** tested method behavior is not a theorem proof. Report
   mathematical claims as checked on the declared finite domain unless separately
   proved. Empirical claims need original/comparable data, split protocol, metric,
   baseline, seeds/repetitions and uncertainty evidence. V1 synthetic smoke cannot
   satisfy them; list exactly what is missing. Code acceptance can coexist with
   explicitly deferred empirical claims, but cannot yield full reproduction.

## Small calibration addition to the planned evaluation

Before a paid workflow comparison, assemble a tiny external, human-adjudicated
fixture set: correct implementations, known semantic faults, invalid properties,
and genuinely ambiguous source passages. Suggested faults include violating a
declared split-isolation contract, incorrect annualization under a frozen
daily-to-annual convention, wrong axis/unit, an always-zero implementation,
and a time-order permutation invariant that should be rejected. These are proposed
calibration cases, not assertions about what a paper specifies.

Measure two distinct capabilities: tests reject known-bad code and accept correct
code; reviewers reject unsupported properties while accepting valid ones and
marking genuine uncertainty as unresolved. Report counts and denominators for
false acceptance, false rejection and unresolved judgments. Inspect disagreements
against the adjudicated source/derivation, never majority vote. One seeded fault
per high-risk property is enough for the initial micro-run; surviving faults call
for inspection rather than an automatic claim that all tests are worthless.

Keep development fixtures separate from final evaluation fixtures. Any final
fixture revealed during repair becomes development evidence and is no longer a
held-out assessment. Include calibration calls and repeated seeds in the same
existing budgets; no automatic expansion, stronger-model fallback or optimizer.
GEPA-based search/tuning belongs strictly to V2.

## Worked fidelity conflict: AlphaEvolve

The inspected local `main.tex` (lines 295–301) says each stock's features use
their maximum over all time steps. Consequently, changing a later observation
can change an earlier normalized value under a literal implementation. A
train-only normalization property must therefore be `engineering_choice` with
an explicit methodological deviation; it is not an entailed paper requirement.
The specification reviewer must identify this conflict before the test author
freezes an incompatible oracle. Preserve the paper claim and record the selected
V1 convention plus its limits; do not silently rewrite the source requirement.
[Paper, Dataset subsection](https://arxiv.org/pdf/2103.16196v2).

Line 342 defines Sharpe using mean return, zero risk-free rate, and standard
deviation, with both statistics annualized over 252 trading days. This wording
does not itself specify every conversion assumption. If the contract chooses
arithmetic daily mean times 252 and daily standard deviation times sqrt(252),
the ratio is sqrt(252) times daily mean/std. Record those assumptions and the
standard-deviation convention; derive a nonzero hand-calculated fixture under
them. Multiplying numerator and denominator by the same 252 is inconsistent
with that frozen convention, but attributing the entire convention directly to
the quoted sentence overstates its specificity.
[Paper, evaluation metric definition](https://arxiv.org/pdf/2103.16196v2).

These cases should be calibration controls: a reviewer should flag the first
property's source misattribution and request the second property's missing
assumptions even when the candidate passes every supplied test.

Not checked: generated tests, actual reviewer accuracy, full data reproduction,
or current upstream commit identity. The principal remaining risk is a convincing
but invalid property shared by author and reviewer; external semantic fixtures
and honest unresolved outcomes reduce that risk without eliminating it.
