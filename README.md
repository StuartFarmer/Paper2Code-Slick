# Paper2Code-Slick

Turn a JSON, Markdown, or LaTeX paper into a Python repository with Slick.
Make a small plan, generate files, run tests, and try up to two repairs. Keep the
code even when verification fails.

![Plan, generate files in parallel, test in Docker, repair, and return the repository.](assets/workflow.svg)

[TikZ source](assets/workflow.tex)

## Setup

```bash
uv sync --group dev
export OPENROUTER_API_KEY="your-openrouter-key"
./scripts/build-executor.sh
```

Or install into your existing Python environment:

```bash
pip install -r requirements.txt
# This installs slick-ai[openai] from PyPI, not a GitHub checkout.
```

Use `python` instead of `uv run python` with that environment. Docker must be running.
The executor contains CPU-only PyTorch, NumPy, pandas, SciPy, PyYAML, pytest and
Hypothesis. The checked-in wheel lock targets Linux ARM64; x86 needs a separately
resolved lock. Generated code runs in Docker with no network or API credentials,
read-only mounts, and resource limits. Checks cannot download datasets or dependencies.

## Run

```bash
uv run python -m codes.workflow \
  /Users/stuart/Developer/AI/arXiv-2103.16196v2/paper/main.tex \
  --model openai/gpt-oss-120b:nitro \
  --output-dir outputs/AlphaEvolve_simple \
  --output-repo-dir outputs/AlphaEvolve_simple_repo \
  2>&1 | tee AlphaEvolve_simple.log
```

Inputs are extracted `.json`, Markdown, or LaTeX files, not PDFs or directories.
LaTeX includes are not expanded: provide consolidated source when the method spans
multiple files. Both output directories must be unused for a new run.

Defaults: `openai/gpt-oss-120b:nitro`, `outputs/Transformer`, and
`outputs/Transformer_repo`. Model names are OpenRouter provider/model IDs;
`:nitro` is preserved. `--planner-model` optionally changes the planning/test model.
This branch currently uses OpenRouter rather than Codex/Claude CLI providers.

## The workflow

1. **Plan:** one call writes a short overview of the algorithm/APIs and a list of
   files with self-contained instructions. No requirement IDs, interface registries,
   dependency graphs, evidence schemas, or approval verdicts.
2. **Generate:** fresh-context workers write different files in parallel. Each sees
   the overview and its own task, including the relevant equations and source details.
3. **Test:** another call writes a small pytest file from the paper and plan. Docker
   checks Python syntax and runs those tests against the combined repository.
4. **Repair:** actual failure logs go directly to a repair prompt. It investigates
   the cause and returns changed production files. Run tests again, at most twice.
5. **Return:** export all generated files and the tests, with a report of what passed
   and what remains unfinished. Successful files survive failed sibling workers,
   model errors, budget exhaustion, and cancellation.

Superpowers contributes prompt guidance: small tasks, explicit APIs, self-review,
root-cause debugging, and checking results before claiming success. These are
instructions to the model, not additional controller gates. The plan and repair
file bundles use small Pydantic schemas with feedback-based JSON repair; code and
tests are plain text. Unsafe paths remain rejected. Repairs cannot rewrite tests.

`complete` means all planned files exist and generated tests passed; it does not
establish scientific reproduction. `draft` means files exist with unresolved work.
The CLI exits zero when it returns complete or draft code, nonzero when no repository
was produced, and 130 on Ctrl-C. The micro evaluation separately judges correctness
using external tests withheld from the workflow.

Generation concurrency defaults to 4 (`--concurrency`). Use `--max-calls` and
`--run-timeout` to bound total calls and seconds. Defaults are 120 calls and one hour.
Malformed structured responses get up to two corrections; production code gets up
to two repair passes. There is no automatic switch to a larger model.

## Logs and resume

Each model call and Docker check prints its stage. The run directory contains:

- `plan.json`: overview and file instructions.
- `generated/`: original generated files; `repairs/`: subsequent changes.
- `calls/`: rendered prompts, raw responses, and call reservations.
- `checks/`: Docker stdout, stderr, and results.
- `report.md`, `report.json`: outcome, export path, warnings, errors and checks.

```bash
uv run python -m codes.workflow --resume outputs/AlphaEvolve_simple
```

Resume reuses saved files and tests, and preserves call/repair budgets. Changed
code, prompts or dependencies require a new run. Runs from the previous strict
workflow are incompatible; retain their logs and start in new directories. If a
resumed result differs from an existing export, its new path is under `exports/`
in the run directory; existing files and user edits are preserved.

## Test the pipeline

```bash
set -o pipefail
uv run python -m eval.run run \
  --stage micro \
  --output-dir outputs/evaluation/nitro-micro-3 \
  2>&1 | tee nitro-micro-3.log
```

The micro trial uses GPT-OSS Nitro with 30 calls and 15 minutes. Its external
acceptance tests never enter generation or repair prompts. A draft can pass this
external evaluation; `workflow_outcome` preserves the workflow's own status.

For controller tests and real Docker integration checks:

```bash
uv run pytest
P2C_TEST_IMAGE=$(docker image inspect paper2code-executor:local --format '{{.Id}}') \
  uv run pytest
```

Planning and test writing see the paper; repair sees the repository. Those calls
can require more context than the per-file workers. Large-paper quality and
published-result reproduction need separate evaluation. See [evaluation notes](eval/README.md).
GEPA remains future work. Earlier detailed design documents under `docs/superpowers/`
are historical and do not describe the current runtime.

Based on [Paper2Code](https://github.com/going-doer/Paper2Code).
Prompt provenance and licenses are recorded in [NOTICE](NOTICE).
