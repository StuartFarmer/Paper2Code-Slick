# Research plan: evidence-grounded property tests

Date: 2026-10-13. Branch: improved. Scope: research and amend the proposed V1
workflow, not implementation or paid evaluation. GEPA is reserved for V2.

Question: how should property-based/metamorphic testing and scientific fidelity
review jointly produce trustworthy acceptance criteria for short-context workers?

1. Property testing: inspect the Trail of Bits skill and primary Hypothesis
   documentation. Establish applicable property classes, generator quality,
   deterministic replay, numerical tolerances, shrinking, and bounded execution.
   Deliver `findings_property_testing.md`; at most five web searches.
2. Scientific fidelity: inspect K-Dense's scientific-critical-thinking guidance
   and primary reproducibility/testing research. Establish source-to-property
   traceability, ambiguity/deviation handling, independent oracles, and limits of
   benchmark-based claims. Deliver `findings_scientific_fidelity.md`; at most five
   web searches.
3. Synthesis: compare findings with the current four improved-workflow documents
   and concrete AlphaEvolve source passages. Define the smallest shared schema,
   prompt handoffs, controller gates, Docker changes, and independent evaluation
   needed. Preserve budgets and source provenance; keep GEPA out of V1.

Evidence rules: use primary sources, cite direct URLs, separate observed source
behavior from proposed adaptations. Do not use popularity as proof of quality.
Do not install skills, execute generated code, build images, or make paid calls.

Completed: both findings files and [integration synthesis](integration.md) are
saved. The four existing improved-workflow documents now incorporate the shared
property contract, source/fidelity gates, Hypothesis executor profile and bounded
calibration. Validated the proposed Pydantic schema/round-trip, worked task JSON,
local document links and diff whitespace. No runtime behavior changed.
