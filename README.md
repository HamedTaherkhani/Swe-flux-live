# repobehave-gen

Automated generator of RepoBehave-style **runtime-behavior QA instances**.
Given a benchmark Docker image (SWE-bench-style, repo at `/testbed`), it
produces N instances (default 40) spanning the 13 question categories
(S1–S6, M1–M7), each authored by its **own isolated agent session** and
harvested end-to-end (traced test run → parser → `oracle.json`).

This project is intentionally detached from the RepoBehave repository; it only
shares the harness contract (tracer, `qa_pipeline.sh`, `oracle.json` schema),
so generated instances drop straight into `qa_instances/<repo>/`.

## Requirements

- Python 3.9+ for the core pipeline (stdlib only — nothing to pip install).
- Docker.
- For `--agent cursor`: `cursor-agent` installed on the host
  (https://cursor.com/docs/cli/installation) and `CURSOR_API_KEY` set.
- For `repogen evaluate` (LLM path): the packages in `requirements.txt`.
  `aider-chat` (RepoMap) needs **Python 3.10–3.12**, so build the venv with one
  of those; on 3.13 use `--repo-map-mode cheap_repomap` / `none` and drop
  `aider-chat` from the requirements.

## Setup (virtualenv)

```bash
cd repobehave-gen
python3.10 -m venv .venv            # 3.10–3.12 so aider-chat installs
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .          # installs the `repogen` console script

.venv/bin/repogen --help            # or: source .venv/bin/activate
```

## Usage

```bash
export CURSOR_API_KEY="..."

# Generate 40 instances for faker
python3 -m repogen generate \
  --repo faker_qa \
  --agent cursor \
  --model gpt-5.3-codex-high \
  --num-instances 40

# Dry run: scout targets + write the allocation plan, generate nothing
python3 -m repogen generate --repo faker_qa --model x --plan-only

# Restrict categories, reuse a cached scout, different seed
python3 -m repogen generate --repo Keras --agent cursor --model gpt-5.3-codex-high \
  --categories S2_Loops,S5_Exceptions,M7_Invariants \
  --targets-json out/Keras/run_.../targets.json --seed 11

# Discover repos / agents / categories
python3 -m repogen list

# Full pipeline: generate + screen + validate in one shot
./scripts/generate_and_screen.sh --repo faker_qa --agent cursor \
  --model gpt-5.3-codex-high --num-instances 40 \
  --solver-model claude-sonnet-4-6

# Screen an existing run (add --dry-run to only report)
python3 -m repogen screen --run-dir out/faker_qa/run_<ts>
python3 -m repogen screen --repo faker_qa            # latest run

# Validate an existing run with a solver agent (needs ANTHROPIC_API_KEY for claude-code)
python3 -m repogen validate --repo faker_qa --solver-model claude-sonnet-4-6

# Add a SECOND model's validation to the same run (outputs stored separately).
# --no-discard records it without pruning; drop it to keep only what both pass.
python3 -m repogen validate --repo faker_qa \
  --solver-agent claude-code --solver-model claude-haiku-4-5-20251001 --no-discard

# Evaluate a run with a raw LLM (no agent) — measurement only, NEVER discards.
# Needs the 'llm' extra installed and the provider API key in .env.
# By default only scores instances at least one agent-validator got right
# (trusted oracles); pass --all-instances to score every instance.
python3 -m repogen evaluate --repo faker_qa \
  --llm-provider anthropic --llm-model claude-haiku-4-5-20251001
```

Repo → image mapping lives in `repositories.json` (same format as RepoBehave's
`Repositories.json`; override any image with `--image`).

## The generation process

Each run is a four-stage pipeline; every stage's output is persisted under
`out/<repo>/run_<timestamp>/`:

1. **Scout** (`payload/scout_targets.py`, runs inside the container,
   deterministic AST analysis): walks the repo, skips tests/vendored code, and
   scores every function on structural features — branches, loops and nesting,
   exception handlers/raises, same-module call fan-out, assignments, size.
   → `targets.json`
2. **Plan** (`planner.py`, deterministic + seeded jitter): allocates the N
   instances across categories. Each category has an *eligibility predicate*
   and an *affinity score* (loops questions need loops; exception questions
   need raise/except; interprocedural questions need local fan-out …).
   Diversity is enforced structurally: a function is used at most once, with
   per-module and per-file caps; quotas are spread evenly with backfill when a
   category runs out of eligible targets. Hardness comes from preferring
   high-complexity targets. → `plan.json`
3. **Generate** (one agent session per instance — never batched): the agent
   receives a prompt assembled from
   `prompts/base_contract.md` (the structural contract: exact file layout,
   `eval.sh` skeleton, parser rules, a 9-step authoring process, and a
   question-wording checklist) + `prompts/categories/<category>.md` (question
   archetypes, answer-definition rules, hardness levers) + the target dossier
   from the scout. The agent writes `files/testcase.py`, `files/parser.py`,
   `eval.sh`, runs `qa_pipeline.sh` itself, checks the oracle is non-trivial
   and byte-stable across two runs, and audits its question wording.
4. **Collect**: the orchestrator copies the instance directory, harvest logs
   (`trace.log`, `pytest.log`, `oracle.log`), the prompt, the agent log and
   trajectory to the host, and appends a status record
   (`generated | agent_failed | no_oracle`) to `manifest.json` after every
   instance — the run is crash-safe.

5. **Screen** (`repogen screen`, deterministic — run separately or via
   `scripts/generate_and_screen.sh`): post-generation runtime exclusion rules.
   Every instance must pass ALL of:
   - `oracle_valid` — oracle.json exists, parses, has the 4 required keys, the
     `question_kind` matches the plan, and `oracle_answer` is not empty;
   - `template_valid` — `template_answer` is a well-formed type skeleton
     (`"str"`/`"int"`/…) and `oracle_answer` structurally conforms to it;
   - `test_passed` — the harvested pytest run passed;
   - `answer_rich` — the answer has enough leaf values for its category;
   - `trace_rich` — the trace shows enough runtime behavior for its category
     (line events, distinct lines, call events, distinct functions, line
     repetitions for loop categories, exception events for exception
     categories). Thresholds live in `screening.CATEGORY_THRESHOLDS`.

   Failing instances are moved to `excluded_instances/` (never deleted) and
   every verdict is recorded in `screening_report.json`.

6. **Validate** (`repogen validate`, agent-based): configurable validation
   stages applied in order (`--validators`, registry in `repogen/validation/`).
   The built-in `solver_agent` validator replays the exact RepoBehave
   evaluation setting: a fresh container, a leak-free bundle per instance
   (question.json with the oracle answer stripped, test files without
   parser/eval.sh), and one isolated solver session (default backend
   `claude-code`, any registered backend works via `--solver-agent`). The
   solver's `answer.json` is scored against the oracle with the benchmark's
   own comparison rules (`repogen/scoring/evaluate_qa_answers.py`, copied
   verbatim from RepoBehave).

   **Multiple models/agents accumulate — nothing is overwritten.** Every run
   is namespaced by `<agent>/<model>` (mirroring RepoBehave's
   `evaluations/<tool>/<model>/`): answers, logs, and trajectories go to
   `validation/solver_agent/<agent>/<model>/<instance>/`, discards to
   `validation_excluded/solver_agent/<agent>/<model>/<instance>/`, and each
   invocation appends its results to the `runs` list in
   `validation_report.json` (the old single-run format is migrated on read).
   So you can validate the same run with several models and keep all their
   outputs side by side. Run sequentially with discarding on (the default), an
   instance survives only if **every** model that validated it passed — each
   new model raises the bar. Pass `--no-discard` to record a model's outputs
   and verdicts without pruning `instances/` (e.g. to compare models on the
   same set).

   The `solver_agent` validator runs a coding agent (`--solver-agent
   claude-code|cursor`) inside the container; it can execute the test, and
   instances it fails are **discarded** — this is a real quality gate.

7. **Evaluate** (`repogen evaluate`, LLM-based, **measurement only**): a raw
   LLM (no agent), ported from RepoBehave's `llm_eval`, that answers each
   instance and is scored against the oracle — but **never discards** anything.
   Use it to measure how models do on the benchmark, not to filter it. It
   snapshots the repo from the image once, then answers with provider APIs
   (`--llm-provider openai|anthropic|gemini|fireworks|openrouter|vllm`,
   `--llm-model ...`) using read-only repo tools
   (`get_repo_map`/`list_dir`/`read_file`); it reasons about behavior
   statically and does **not** execute code. Per-instance answers, token usage,
   and USD cost (pricing from `repogen/llm_eval/provider_model_costs.json`) are
   written under `evaluation/llm/<provider>/<model>/<instance>/`, summarized in
   that folder's `run_summary.json`, and accumulated across models in
   `evaluation_report.json`. Requires the `llm` extra: `pip install -e '.[llm]'`
   (aider-chat only for `--repo-map-mode repomap`; use `cheap_repomap`/`none`
   otherwise).

   So: **agents validate (and can prune); LLMs only evaluate.** The two write
   to separate trees (`validation/` vs `evaluation/`) and separate reports, and
   `validate` refuses evaluation-only stages (and vice versa).

   By default `evaluate` only scores instances that **at least one
   agent-validator got right** (the union of passed instances across
   `solver_agent` runs in `validation_report.json`) — an agent solving an
   instance is evidence its oracle is sound, so this skips instances no agent
   could solve (often buggy oracles). Pass `--all-instances` to score every
   instance in `instances/` regardless.

Repair loops and certification are deliberately out of scope; screening and
validation only discard instances, evaluation never does — none of them modify
instances.

## Output layout

```
out/<repo>/run_<ts>/
├── run_config.json        # full config of the run
├── targets.json           # scout inventory
├── plan.json              # category × target allocation
├── manifest.json          # per-instance status, updated live
├── instances/             # complete drop-in QA folder (like qa_instances/<repo>)
│   ├── qa_pipeline.sh     # in-container stage+eval pipeline
│   ├── run_qa_fromhost.sh # host runner, image pre-rendered for this repo
│   ├── run_all_qa_fromhost.sh
│   ├── shared/files/      # trace_plugin.py + conftest.py (same for all repos)
│   └── <instance_id>/     # eval.sh, files/, oracle.json
├── logs/<id>/             # prompt.md, agent log + traj, harvest/ logs
├── screening_report.json
├── excluded_instances/    # screened-out instances
├── validation/solver_agent/<agent>/<model>/<instance>/   # per-model agent-solver outputs
├── evaluation/llm/<provider>/<model>/<instance>/         # per-model LLM-eval outputs (answer/debug/trace/cost)
├── evaluation_report.json                                # accumulates LLM evaluation runs
├── validation_excluded/solver_agent/<agent>/<model>/<instance>/
└── validation_report.json # accumulates one entry per (agent, model) run
```

`instances/` is runnable from host exactly like the original benchmark:

```bash
cd out/<repo>/run_<ts>/instances
./run_qa_fromhost.sh <instance_id>   # re-harvest one instance
./run_all_qa_fromhost.sh             # re-harvest everything -> qa_artifacts/
```

## Architecture / extension points

- **Agent backends** (`repogen/agents/`): Strategy + Registry. Implement
  `AgentBackend.prepare()` (install CLI into container) and `run_task()` (one
  stateless session per prompt), decorate with `@register` — it appears in
  `--agent` / `--solver-agent` automatically. `cursor` and `claude-code` are
  implemented; `codex` is a registered placeholder.
- **Validators** (`repogen/validation/`): Strategy + Registry. Implement
  `Validator.validate(ctx) -> [ValidationVerdict]`, decorate with `@register`,
  and select stages with `--validators a,b,c` (applied in order; instances
  discarded by one stage are not seen by later ones). Discarding and
  reporting are handled by the shared runner — validators only judge.
- **Categories** (`repogen/prompts/categories/*.md` + `planner.CATEGORY_PROFILES`):
  adding a category = one markdown card + one `CategoryProfile`
  (eligibility + affinity).
- **Prompt contract** (`repogen/prompts/base_contract.md`): edit without
  touching code; `{{TOKEN}}` substitution only.
- **Harness payload** (`repogen/payload/`): tracer, conftest, `qa_pipeline.sh`,
  scout — staged into each container verbatim.
- **Docker** (`docker_env.py`): a single `Container` facade; everything else is
  docker-agnostic.
