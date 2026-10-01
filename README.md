# RepoBehave instance generator

Generate repository-level runtime-behavior QA instances, validate that they are
solvable, run models in the paper's static setting, and report exact accuracy
and partial credit.

```text
generate -> screen -> validate -> evaluate -> score
```

Every run is stored under `out/<repo>/run_<timestamp>/`.

## Setup

Requirements: Python 3.10–3.12, Docker, and whichever agent CLIs you use
(`cursor-agent`, `claude`, or `codex`).

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[llm]'
docker info
repogen list
```

The benchmark image must contain the repository at `/testbed`. Use a repository
already listed in `repositories.json`, add `"my_repo": "registry/image:tag"`,
or pass `--image registry/image:tag` to `repogen generate`.

Put the required keys in the project-root `.env`, for example
`CURSOR_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MOONSHOT_API_KEY`,
`FIREWORKS_API_KEY`, or `DEEPSEEK_API_KEY`. Claude Code and Codex may use their
existing host CLI login. Do not commit `.env`.

## Generate a benchmark run

This creates 40 instances across the 13 categories, with one independent agent
session per instance:

```bash
repogen generate \
  --repo my_repo \
  --agent cursor \
  --model <generation-model> \
  --num-instances 40 \
  --parallel 6

RUN_DIR=out/my_repo/run_<timestamp>
```

`--agent` may be `cursor`, `claude-code`, or `codex`. The command prints the
actual run directory.

Screen the generated instances, then record three independent validation
attempts per survivor:

```bash
repogen screen --run-dir "$RUN_DIR"

repogen validate \
  --run-dir "$RUN_DIR" \
  --solver-agent claude-code \
  --solver-model claude-haiku-4-5-20251001 \
  --rollouts 3 \
  --parallel 6 \
  --no-discard
```

`--no-discard` keeps the screened set while recording all validation results.
The paper's gate considers an instance verified when at least one approved
Haiku or Fable rollout exactly matches its oracle. Evaluation applies this gate
by default. Omit `--no-discard` only if validation failures should be moved out
of `instances/`.

## Run inference

Inference saves one `answer.json` per instance and never removes instances.
Re-running the same scope resumes incomplete work.

### Raw LLM API, without code execution

```bash
repogen evaluate \
  --run-dir "$RUN_DIR" \
  --llm-provider kimi \
  --llm-model kimi-k3 \
  --parallel 6
```

Replace the provider and model as needed. Supported providers include
`openai`, `anthropic`, `gemini`, `fireworks`, `deepseek`, `openrouter`, `vllm`,
`kimi`, and `groq`; see `repogen evaluate --help`.

### Claude Code, without code execution

```bash
repogen evaluate \
  --run-dir "$RUN_DIR" \
  --evaluators solver_agent_noexec \
  --agent claude-code \
  --agent-model claude-opus-5-5 \
  --agent-effort medium \
  --parallel 6
```

### Codex, without code execution

```bash
repogen evaluate \
  --run-dir "$RUN_DIR" \
  --evaluators solver_agent_noexec \
  --agent codex \
  --agent-model gpt-6-sol \
  --agent-effort medium \
  --parallel 6
```

The no-execution evaluator exposes a read-only repository in a minimal sandbox
without Python, pytest, or project dependencies. Cursor is not supported by
this evaluator; use it for generation or execution-enabled inference:

```bash
repogen validate --run-dir "$RUN_DIR" \
  --solver-agent cursor --solver-model <cursor-model> \
  --parallel 6 --no-discard
```

Use `--all-instances` with `repogen evaluate` only to bypass the default
solvability gate deliberately.

## Report exact accuracy and partial credit

`repogen decompose` re-scores existing answers without making model calls. It
prints strict exact-match accuracy and mean partial credit and saves both in a
JSON report:

```bash
repogen decompose \
  --all-runs \
  --output-root out \
  --evaluation-scope kimi/kimi-k3 \
  --report out/kimi_scores.json
```

For one run, replace `--all-runs --output-root out` with
`--run-dir "$RUN_DIR"`. Use the exact scope recorded in
`evaluation_report.json`. Examples are:

```text
kimi/kimi-k3
claude-code-noexec/claude-opus-5-5-medium
codex-noexec/gpt-6-sol-medium
```

Read the headline values with:

```bash
jq '.scopes["kimi/kimi-k3"].summary |
    {answers, exact, exact_rate, mean_score}' out/kimi_scores.json
```

- `exact_rate` is strict accuracy in `[0,1]`.
- `mean_score` is mean partial credit in `[0,1]`.

For Cursor or another execution-enabled validator, score the validation tree:

```bash
repogen decompose --run-dir "$RUN_DIR" \
  --source validation \
  --evaluation-scope agent:cursor/<cursor-model> \
  --report out/cursor_scores.json
```

Run inference to completion before reporting results: `decompose` scores saved
answers, so resume an interrupted evaluation first.

## Reproduce the paper analyses

### Difficulty calibration

```bash
repogen complexity --all-runs --output-root out \
  --report out/complexity_report.json

python3 scripts/calibrate_difficulty.py \
  --complexity-report out/complexity_report.json

# Refresh scores with the newly frozen calibration.
repogen complexity --all-runs --output-root out \
  --report out/complexity_report.json

python3 scripts/difficulty_label_agreement.py \
  --complexity-report out/complexity_report.json \
  --output out/difficulty_label_agreement.json
```

Both Python scripts accept repeated `--scope <evaluation-scope>` arguments to
select the evaluated models.

### Input-only perturbation

```bash
repogen perturb \
  --run-dir "$RUN_DIR" \
  --proposer agent \
  --agent cursor \
  --agent-model <generation-model> \
  --complexity-report out/complexity_report.json \
  --agent-parallel 6
```

Perturbed runs are written under `out/perturbation/`; pass a perturbed
repository directory to the same `evaluate` and `decompose` commands.

### Required-code trajectory evaluation

```bash
repogen evidence --all-runs --output-root out --harvest --parallel 6

repogen required-code --all-runs --output-root out \
  --agent claude-code --model claude-opus-5-5 \
  --effort medium --parallel 6

repogen evidence --all-runs --output-root out \
  --evaluation-scope kimi/kimi-k3 \
  --report out/evidence_report.json
```

Repeat the last command for each evaluated model.

## Main outputs

```text
out/<repo>/run_<timestamp>/
├── instances/                 # generated benchmark instances and oracles
├── logs/                      # generation logs and execution traces
├── screening_report.json
├── validation_report.json
├── evaluation_report.json
├── validation/                # execution-enabled solver outputs
└── evaluation/                # raw-LLM and no-execution agent outputs
```

Use `repogen <command> --help` for category filters, instance subsets,
timeouts, repository-map modes, and output-path options.
