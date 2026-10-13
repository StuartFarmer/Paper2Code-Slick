# Paper2Code-Slick

Generate a code repository from a research paper using one Slick workflow.
A single `PaperCoder` class plans the implementation, analyzes each file, and
writes code in dependency order. Model instructions live in six local Jinja
templates.

This fork adapts [Paper2Code](https://github.com/going-doer/Paper2Code). It retains
the three-stage method and prompt wording while replacing the separate scripts
and provider-specific implementations with Slick sessions and providers.

![Slick workflow: paper input, four planning calls in a shared session, independent per-file analysis, sequential coding with previously written code, and a generated repository.](assets/workflow.svg)

[TikZ source](assets/workflow.tex)

## Run it

Use Python 3.10+ and keep the Slick checkout beside this repository:

```text
AI/
├── slick/
└── Paper2Code-Slick/
```

From this repository's root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="<your-api-key>"

python -m codes.workflow examples/Transformer.json \
    --model o3-mini \
    --output-dir outputs/Transformer \
    --output-repo-dir outputs/Transformer_repo
```

The JSON input is a paper extracted from a PDF, not the PDF itself. Extraction
metadata is removed automatically. For LaTeX, pass
`examples/Transformer_cleaned.tex` instead. To prepare a PDF, use a converter
such as [s2orc-doc2json](https://github.com/allenai/s2orc-doc2json) first.

The CLI defaults to `o3-mini`, `outputs/Transformer`, and
`outputs/Transformer_repo`. Set both output paths when starting a separate run:
matching files are overwritten, and unrelated existing files are retained.

## How the workflow runs

1. **Plan.** Four calls share one session: reproduction overview, architecture
   and interfaces, ordered file tasks, and configuration. The workflow validates
   the task list and generated paths before writing the repository.
2. **Analyze.** Each planned file gets a fresh session containing the paper,
   plan, design, task list, and config. All file analyses finish before coding
   begins.
3. **Code.** Files are generated sequentially in task order. Each call gets a
   fresh session with that file's analysis and previously generated source code.
   `config.yaml` comes from planning and is not generated again.

A successful run makes **4 + 2N model calls**, where N is the number of planned
files other than `config.yaml`. Analysis calls have independent context but run
sequentially too. The workflow writes code; it does not execute it, install its
dependencies, or evaluate whether it reproduces the paper.

Planning JSON must be valid. Invalid output and provider errors stop the run
without automatic retries or repair. Partial files and call logs remain on disk.
Rerunning starts from planning; this CLI does not enable persistent workflow
resume. Generated paths cannot escape the output directory or use hidden paths
or symlinks beneath it.

## Outputs

```text
outputs/
├── Transformer/
│   ├── planning/
│   │   ├── overview.txt
│   │   ├── design.json
│   │   ├── tasks.json
│   │   └── config.yaml
│   ├── analysis/
│   │   └── <filename>.txt
│   ├── calls/
│   │   ├── planning.json
│   │   ├── analysis/<filename>.json
│   │   └── coding/<filename>.json
│   └── failure.json                 # model-call or empty-response failure
└── Transformer_repo/
    ├── config.yaml
    └── ...generated files
```

Nested filenames retain their directories. Call logs contain Slick session
history, including the rendered context, raw response text, and tool work.
Responses remain available even if later parsing fails. No token or cost
reports are produced.

## Use a local model

The same workflow can call an OpenAI-compatible chat endpoint through Slick's
LiteLLM provider. For a vLLM server, install Slick's extra in the workflow
environment:

```bash
pip install -e '../slick[litellm]'
export OPENAI_API_KEY="local"  # substitute your server's key if required

python -m codes.workflow examples/Transformer.json \
    --model deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct \
    --api-base http://localhost:8000/v1 \
    --output-dir outputs/Transformer_dscoder \
    --output-repo-dir outputs/Transformer_dscoder_repo
```

Start the server separately in your GPU environment, with vLLM installed:

```bash
vllm serve deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct --tensor-parallel-size 2
```

The CLI uses `OpenAIAPI` by default and `LiteLLMAPI` when `--api-base` is supplied.
Both use a 600-second timeout with no retries. Output caps are 32,768 tokens for
OpenAI and 8,192 for compatible chat endpoints.

## Convenience scripts

These launch the same workflow with the bundled Transformer inputs:

| Script | Input | Provider |
| --- | --- | --- |
| `bash scripts/run.sh` | JSON | OpenAI |
| `bash scripts/run_latex.sh` | LaTeX | OpenAI |
| `bash scripts/run_llm.sh` | JSON | Compatible chat endpoint |
| `bash scripts/run_latex_llm.sh` | LaTeX | Compatible chat endpoint |

Override `PAPER_PATH`, `MODEL_NAME`, `OUTPUT_DIR`, `OUTPUT_REPO_DIR`, or `PYTHON`
through environment variables. The local-model scripts also accept `API_BASE`
(default: `http://localhost:8000/v1`). Append CLI flags to override other defaults.
The scripts change into the repository root before resolving input and output
paths; invoke the script by its full path when working elsewhere.

## Python API

Set the process-wide template root once at application startup and inject a
Slick provider. Use one `PaperCoder` instance per run.

```python
import asyncio
from pathlib import Path

from slick import prompts
from slick.providers import OpenAIAPI

from codes import workflow

prompts.TEMPLATE_ROOT = Path(workflow.__file__).resolve().parent / "prompts"
paper, paper_format = workflow.load_paper(Path("examples/Transformer.json"))
coder = workflow.PaperCoder(
    paper,
    paper_format,
    OpenAIAPI("o3-mini", max_output_tokens=32768, timeout=600),
    Path("outputs/Transformer"),
    Path("outputs/Transformer_repo"),
)
asyncio.run(coder.run())
```

## Development

| Path | Purpose |
| --- | --- |
| [`codes/workflow.py`](codes/workflow.py) | Prompt methods, orchestration, file writing, CLI |
| [`codes/paper.py`](codes/paper.py) | JSON cleanup and paper loading |
| [`codes/prompts/`](codes/prompts/) | Overview, design, tasks, config, analysis, and coding templates |
| [`tests/`](tests/) | Offline checks with a scripted provider |
| [`data/`](data/) and [`examples/`](examples/) | Paper data and reference repositories |

Run the offline tests without API credentials or a GPU:

```bash
pip install pytest
python -m pytest
```

To rebuild the diagram, install a TeX distribution with TikZ and `pdftocairo`
(Poppler), then run from the repository root:

```bash
mkdir -p /tmp/paper2code-slick-diagram
pdflatex -interaction=nonstopmode -halt-on-error \
    -output-directory=/tmp/paper2code-slick-diagram assets/workflow.tex
pdftocairo -svg /tmp/paper2code-slick-diagram/workflow.pdf assets/workflow.svg
```

Commit both the `.tex` source and the rendered `.svg`; GitHub displays the SVG.

## Origin and scope

Based on *Paper2Code: Automating Code Generation from Scientific Papers in
Machine Learning* by Minju Seo, Jinheon Baek, Seongyun Lee, and Sung Ju Hwang.
See the [paper](https://arxiv.org/abs/2504.17192),
[upstream repository](https://github.com/going-doer/Paper2Code), and
[benchmark data](data/paper2code/README.md).

This fork combines the original system and user instructions into Slick prompt
context and changes provider settings. The original paper's benchmark results
have not been revalidated for this implementation. The numbered pipeline,
standalone evaluator, configuration-refinement tool, and debugger are removed.
