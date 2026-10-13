# Paper2Code-Slick

Turn a JSON, Markdown, or LaTeX paper into a Python repository and an experiment
notebook with Slick. Make a small plan, generate files, run tests, try up to two
repairs, then write the notebook. Keep the code even when verification fails.

![Plan, generate files in parallel, test in Docker, repair, and export the experiment notebook and repository.](assets/workflow.svg)

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
3. **Test:** another call inspects the paper, plan and generated code, then writes
   granular pytest tests. Each test covers one behavior with explicit Arrange,
   Act and Assert sections. Target every public function/method, branch, boundary,
   and exception path. Docker checks syntax, runs tests, and measures statement
   and branch coverage of production Python files, including unimported modules.
4. **Repair:** actual failure logs go directly to a repair prompt. It investigates
   the cause and returns changed production files. Run tests again, at most twice.
5. **Notebook:** one fresh-context call uses the paper, plan, final code and test
   status to write `experiment.ipynb`. Its cells import the implementation, configure
   and conduct the experiment, calculate metrics, plot results, and discuss the
   comparison with the paper. Small demonstrations and missing data/compute must
   be clearly identified. The notebook is generated, **not executed** by the pipeline.
6. **Return:** export the notebook, generated files and tests, with a report of what passed
   and what remains unfinished. Successful files survive failed sibling workers,
   model errors, budget exhaustion, and cancellation.

Superpowers contributes prompt guidance: small tasks, explicit APIs, self-review,
root-cause debugging, and checking results before claiming success. These are
instructions to the model, not additional controller gates. The plan and repair
file bundles and notebook cells use small Pydantic schemas with feedback-based
JSON repair; code and tests are plain text. Unsafe paths remain rejected. Repairs
cannot rewrite tests or the separately authored notebook.

`complete` means all planned files and the notebook exist and generated tests passed;
it does not establish that notebook cells ran or scientific results were reproduced.
`draft` means files exist with unresolved work. A notebook-generation failure keeps
the implementation and tests as a draft. Earlier model errors, cancellation, or
exhausted budgets may prevent the notebook step from being reached.
The CLI exits zero when it returns complete or draft code, nonzero when no repository
was produced, and 130 on Ctrl-C. The micro evaluation separately judges correctness
using external tests withheld from the workflow.

The test-generation target is 100% statement and branch coverage with meaningful
assertions. Actual percentages, missing lines, and branch lines with uncovered exits
are recorded under `coverage` in `report.json` and each pytest check's `result.json`.
`report.md` shows percentages (`n/a` when no statements/branches were measurable).
Coverage below 100% does not block export or trigger an unbounded test-writing loop.
The initial test call aims for full coverage; gaps remain visible for follow-up.
Coverage is measured in the pytest process; separately spawned processes are not
tracked. Full coverage alone does not establish correctness or scientific fidelity.

Generation concurrency defaults to 4 (`--concurrency`). Use `--max-calls` and
`--run-timeout` to bound total calls and seconds. Defaults are 120 calls and one hour.
Malformed structured responses get up to two corrections; production code gets up
to two repair passes. There is no automatic switch to a larger model.

## Run the experiment notebook

The final deliverable is `<export_path>/experiment.ipynb`; find the actual export
path in `report.json`. From that repository, install its generated requirements
(when present), plus JupyterLab and matplotlib in your chosen environment. For example:

```bash
cd outputs/AlphaEvolve_simple_repo
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt  # when present
uv pip install --python .venv/bin/python jupyterlab matplotlib
.venv/bin/jupyter lab experiment.ipynb
```

Read the setup and configuration cells, provide required datasets, then use **Run
All Cells**. These cells execute in your selected Jupyter environment, outside the
pipeline's Docker test sandbox. The notebook includes experiment code and plotting
cells; output cells start empty. Large experiments may require additional data or
hardware. Passing unit tests does not establish that the experiment will run or
match the paper's published results.

## Logs and resume

Each model call and Docker check prints its stage. The run directory contains:

- `plan.json`: overview and file instructions.
- `generated/`: original generated files; `repairs/`: subsequent changes.
- `calls/`: rendered prompts, raw responses, and call reservations.
- `checks/`: Docker stdout, stderr, and results.
- `notebooks/`: cached notebook keyed by its final code and input context.
- `report.md`, `report.json`: outcome, export path, warnings, errors, checks, coverage,
  and notebook path/status (`unexecuted` or `not_generated`).

```bash
uv run python -m codes.workflow --resume outputs/AlphaEvolve_simple
```

Resume reuses saved files, tests and matching notebooks, and preserves call/repair budgets. Changed
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

Planning sees the paper; test writing and repair also see the repository. Those calls
can require more context than the per-file workers. Large-paper quality and
published-result reproduction need separate evaluation. See [evaluation notes](eval/README.md).
GEPA remains future work. Earlier detailed design documents under `docs/superpowers/`
are historical and do not describe the current runtime.

Based on [Paper2Code](https://github.com/going-doer/Paper2Code).
Prompt provenance and licenses are recorded in [NOTICE](NOTICE).
