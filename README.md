# 📄 Paper2Code: Automating Code Generation from Scientific Papers in Machine Learning

**Minju Seo, Jinheon Baek†, Seongyun Lee, and Sung Ju Hwang†** († denotes equal advising)  
International Conference on Learning Representations (ICLR), 2026  
📄 [Read the paper](https://arxiv.org/abs/2504.17192)  

![PaperCoder Overview](./assets/papercoder_overview.png)

**PaperCoder** is the multi-agent LLM system introduced in **Paper2Code**, designed to transform a paper into a code repository.
It follows a three-stage pipeline: planning, analysis, and code generation, each handled by specialized agents.
Our method outperforms strong baselines on both Paper2Code and PaperBench and produces faithful, high-quality implementations.

---

## 🗺️ Table of Contents

- [⚡ Quick Start](#-quick-start)
- [📚 Detailed Setup Instructions](#-detailed-setup-instructions)
- [📦 Paper2Code Benchmark Datasets](#-paper2code-benchmark-datasets)

---

## ⚡ Quick Start

PaperCoder runs as one Slick workflow: four planning calls share a session,
then every file is analyzed independently and implemented in dependency order.
The six prompt templates live in `codes/prompts/`; the original prompt wording
and tagged response formats are retained. Each template combines the former
system and user instructions into Slick's user context, so this is not an exact
reproduction of the original message roles or model settings.

Install Python 3.10+ and the adjacent Slick checkout:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # expects ../slick
export OPENAI_API_KEY="<OPENAI_API_KEY>"

python -m codes.workflow examples/Transformer.json \
    --model o3-mini \
    --output-dir outputs/Transformer \
    --output-repo-dir outputs/Transformer_repo
```

JSON extraction metadata is cleaned automatically. To use LaTeX, pass
`examples/Transformer_cleaned.tex` instead. Convenience commands also
work from any directory:

```bash
bash scripts/run.sh
bash scripts/run_latex.sh
```

The scripts accept `PAPER_PATH`, `MODEL_NAME`, `OUTPUT_DIR`, `OUTPUT_REPO_DIR`,
and `PYTHON` environment overrides. Relative paths are resolved from this repository.
Additional CLI flags can be appended to the script command.

```text
outputs/
├── Transformer/
│   ├── planning/       # overview, design, tasks, and config
│   ├── analysis/       # per-file logic analysis
│   └── calls/          # raw Slick session histories
└── Transformer_repo/
    ├── config.yaml
    └── ...generated files
```

The workflow writes files but does not execute generated code. Existing files
with the same names are overwritten; use a new output directory for a separate
run. Generated paths cannot traverse outside the output directories or use
hidden paths or symlinks below them. Calls are sequential with no automatic
retries. Raw Slick session histories are saved after each call, including
responses rejected during parsing; model call failures also write `failure.json`.
Planning JSON must be valid; malformed model output is rejected without repair.
A failed run leaves partial artifacts and files. Rerunning starts from planning;
`@workflow` alone does not enable persistent resume.

`calls/planning.json` contains the four planning exchanges;
`calls/analysis/<filename>.json` and `calls/coding/<filename>.json` contain
independent file exchanges. Each record uses Slick's session-history format,
including `context`, `text`, and tool work. There are no OpenAI response envelopes
or token/cost reports. OpenAI uses Slick's Responses provider with a 32,768-token
output cap and its default reasoning setting; compatible chat endpoints use an
8,192-token cap.

The numbered pipeline scripts and standalone evaluation, configuration-refinement,
and debugging commands have been removed. Use `python -m codes.workflow` or the
shell launchers above. Paper data and reference repositories remain in `data/`
and `examples/`.

## 📚 Detailed Setup Instructions

### Open-source models with vLLM

Start an OpenAI-compatible vLLM server in your GPU environment:

```bash
pip install vllm
vllm serve deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct --tensor-parallel-size 2
```

In the workflow environment, install Slick's chat provider extra and run:

```bash
pip install -e '../slick[litellm]'
export OPENAI_API_KEY="local"  # use your server's key if authentication is enabled
bash scripts/run_llm.sh
# Or: bash scripts/run_latex_llm.sh
```

Set `API_BASE` to change the default `http://localhost:8000/v1`, or pass
`--api-base` and `--model` directly to `python -m codes.workflow`.

### Python API and tests

Configure the template root once at application startup, then inject a Slick
provider. The root is process-global.

```python
import asyncio
from pathlib import Path
from slick import prompts
from slick.providers import OpenAIAPI
from codes import workflow

prompts.TEMPLATE_ROOT = Path(workflow.__file__).resolve().parent / "prompts"
paper, paper_format = workflow.load_paper(Path("examples/Transformer.json"))
coder = workflow.PaperCoder(
    paper, paper_format, OpenAIAPI("o3-mini", max_output_tokens=32768, timeout=600),
    Path("outputs/Transformer"), Path("outputs/Transformer_repo"),
)
asyncio.run(coder.run())
```

The offline tests use a scripted provider and never call a model:

```bash
pip install pytest
python -m pytest
```

### 📄 (Option) Convert PDF to JSON
The following process describes how to convert a paper PDF into JSON format.  
If you have access to the LaTeX source and plan to use it with PaperCoder, you may skip this step and proceed to [⚡ Quick Start](#-quick-start).
Note: In our experiments, we converted all paper PDFs to JSON format.

1. Clone the `s2orc-doc2json` repository to convert your PDF file into a structured JSON format.  
   (For detailed configuration, please refer to the [official repository](https://github.com/allenai/s2orc-doc2json).)

```bash
git clone https://github.com/allenai/s2orc-doc2json.git
```

2. Run the PDF processing service.

```bash
cd ./s2orc-doc2json/grobid-0.7.3
./gradlew run
```

3. Convert your PDF into JSON format.

```bash
mkdir -p ./s2orc-doc2json/output_dir/paper_coder
python ./s2orc-doc2json/doc2json/grobid2json/process_pdf.py \
    -i ${PDF_PATH} \
    -t ./s2orc-doc2json/temp_dir/ \
    -o ./s2orc-doc2json/output_dir/paper_coder
```

---

## 📦 Paper2Code Benchmark Datasets
- Huggingface dataset: [paper2code](https://huggingface.co/datasets/iaminju/paper2code)
  
- You can find the description of the Paper2Code benchmark dataset in [data/paper2code](https://github.com/going-doer/Paper2Code/tree/main/data/paper2code). 
- For more details, refer to Section 4.1 "Paper2Code Benchmark" in the [paper](https://arxiv.org/abs/2504.17192).
