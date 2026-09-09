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

# Validate an existing run with a solver agent. claude-code auths with
# CLAUDE_CODE_OAUTH_TOKEN (subscription — create via `claude setup-token`)
# or ANTHROPIC_API_KEY (API billing); the OAuth token wins when both are set.
python3 -m repogen validate --repo faker_qa --solver-model claude-sonnet-4-6

# Add a SECOND model's validation to the same run (outputs stored separately).
# --no-discard records it without pruning; drop it to keep only what both pass.
python3 -m repogen validate --repo faker_qa \
  --solver-agent claude-code --solver-model claude-haiku-4-5-20251001 --no-discard

# Tiered agent validation, weakest model first. Failures escalate and instances
# every tier fails are discarded. These results are validation evidence only;
# they are saved in validation_report.json and cascade_validation_report.json.
python3 -m repogen cascade --repo haystack --rollouts 2 \
  --tier haiku_all=claude-code:claude-haiku-4-5-20251001 \
  --tier sonnet_all=claude-code:claude-sonnet-4-6 \
  --tier fable_all=claude-code:claude-fable-5

# Evaluate a run with a raw LLM (no agent) — measurement only, NEVER discards.
# Needs the 'llm' extra installed and the provider API key in .env.
# By default only scores instances where at least one Haiku or Fable rollout
# matched the oracle. --all-instances is an explicit safeguard override.
python3 -m repogen evaluate --repo faker_qa \
  --llm-provider anthropic --llm-model claude-haiku-4-5-20251001

# Kimi / Moonshot (OpenAI-compatible, https://api.moonshot.ai/v1).
# Needs MOONSHOT_API_KEY (or kimi_api_key) in .env and a funded account.
# K3 always reasons and fixes its sampling params, so --llm-temperature is
# ignored. --llm-reasoning-effort defaults to medium; K3 only accepts
# low|high|max, so medium maps to high (logged when it happens).
python3 -m repogen evaluate --repo faker_qa \
  --llm-provider kimi --llm-model kimi-k3 --parallel 6

# Compute model-independent complexity labels, then report Kimi accuracy in
# easy/medium/hard/very_hard bins for each metric and their fixed combination.
# No cascade labels, validation reports, or Haiku/Fable rollout logs are read.
python3 -m repogen complexity --all-runs --output-root out \
  --evaluation-scope kimi/kimi-k3
```

### Intrinsic complexity metrics

`repogen complexity` scores every instance from 0 to 10 on three dimensions:

- **semantic reasoning** — execution-grounded control flow, changed-state
  events, calls and call depth, exceptions, and the exact path/repetition
  workload. Static target complexity is retained only as supporting context,
  so branches the test never executes cannot dominate the label;
- **answer construction** — answer leaves, ordered elements, structural depth,
  and the amount of exact string/numeric content to produce;
- **repository navigation** — navigation uncertainty after accounting for the
  signposts supplied by the instance: an executable entrypoint, explicit file
  and function clues, testcase context, and API centrality, plus the number of
  distinct source lines reached by the harvested execution. Navigation is 70%
  uncertainty (`10 - support`) and 30% saturating executed-code footprint.
  Repeated execution of one line does not increase the footprint.

The combined score is fixed at 40% semantic reasoning, 35% answer construction,
and 25% repository navigation. By default, each score is divided into `easy`,
`medium`, `hard`, and `very_hard` at the 25th, 50th, and 75th percentiles within
the same answer archetype. Repository navigation alone uses global quartiles by
default because navigation burden is comparable across answer schemas; this
keeps its four levels close to equal size. Override that with
`--navigation-stratify-by` when needed. Use `--stratify-by none` for pooled global quantiles, or choose
`category`/`category_archetype` for other comparisons.

Scoring and binning use only `plan.json`, the harvested trace, `oracle.json`,
`testcase.py`, and `eval.sh`. If `evaluation_report.json` is present, its
pass/fail outcomes are joined only after bins are frozen to report held-out
accuracy; they never affect scores, thresholds, or labels. Full features,
component scores, thresholds, per-instance labels, and accuracy tables are
written to `complexity_report.json`.

Intrinsic scoring owns the canonical difficulty artifacts. At generation
completion—and again after screening or validation changes the current instance
set—the pipeline refreshes pooled thresholds, writes `difficulty_report.json`
in every run, and writes each instance's `difficulty.json`. Those files contain
all three metric scores and labels plus the combined score and label. Haiku and
Fable results never enter these scores; they remain in validation artifacts.

### Intrinsic-complexity perturbation

Perturbation uses the combined intrinsic metric by default. Its source pool is
the intersection of:

- instances still present in `instances/` and not listed as cascade/manual
  exclusions;
- instances labelled `easy` by `difficulty.combined` in the frozen complexity
  report; and
- instances for which at least one Haiku or Fable rollout matched the oracle.
  Partial validation success counts as evidence of solvability.

The proposer receives the source instance's scorecard and optimizes the same
fixed combination: semantic reasoning 40%, answer construction 35%, and
repository navigation 25%. The prompt requires input-only hardening and asks
each of the three component scores to increase; distinct executed lines must be
reached through harder data, not added test code. Each harvested candidate is scored again using the
source plan metadata and the frozen source-report thresholds. By default it is
kept only when its combined score increases and reaches at least the `medium`
bin. Accepted candidates receive an intrinsic `difficulty.json`, and the
perturbed run gets a `complexity_report.json` containing the candidate scores
and labels under the frozen source thresholds; the small candidate set is not
re-binned against itself.

Each proposal prompt includes a per-instance diagnosis that orders the three
metrics from easiest to hardest, gives the exact next-bin boundary, lists every
measured submetric and its raw evidence, and maps actionable submetrics to
specific input-only hardening levers. Fixed or inverse navigation signals are
marked explicitly so the proposer does not game difficulty by removing clues or
rewriting test structure. Feedback retries also receive the previous
candidate's measured submetrics and raw evidence.

```bash
# First freeze intrinsic scores/thresholds for the source collection.
python3 -m repogen complexity --all-runs --output-root out \
  --report out/complexity_report.json

# Default: validated combined-easy sources -> medium-or-hard candidates.
python3 -m repogen perturb --run-dir out/<repo>/run_<ts> \
  --proposer agent --agent cursor \
  --complexity-report out/complexity_report.json
```

The default destination is `out/perturbation/`. Pass
`--keep-below-complexity-target` for measurement batches where valid candidates
that remain easy should be retained and labelled instead of discarded. Test
setup and call changes are allowed by default; `--enforce-structure` opts into
the retained legacy AST check. `--reuse-staged-variants` resumes an interrupted
run without repeating completed proposer calls.

Use `--complexity-target hard` for a stricter gate, or `increased` to accept any
positive combined-score change. The historical downstream-model flip logic is
still available through `--flip-check` / `--require-flip`, but it is opt-in and
is not consulted by the default selection, prompt, scoring, or acceptance path.
For a legacy run with no intrinsic gate, pass
`--source-selection all --complexity-target none`.

### Observed validator effort

`repogen rollout-effort` analyzes solver-agent validation trajectories without
changing intrinsic difficulty labels. It records every rollout's tool counts
and errors, files read/touched, source exploration, searches, shell/test runs,
instrumentation and helper files, answer writes/revisions, assistant turns,
estimated thinking tokens, input/output/cache tokens, duration, cost, and time
to first tool/execution/answer.

Five raw effort dimensions are converted to percentile ranks within each model
so Haiku and Fable are not compared on incompatible token/time scales:

- exploration 25% — tool use, repository/source files, searches, read volume;
- execution 25% — shell/Python/test runs, instrumentation, writes and edits;
- deliberation 25% — turns, estimated thinking tokens, output tokens;
- friction 10% — tool errors, repeated commands, answer revisions, denials;
- resources 15% — elapsed time and context-token volume.

The weighted result is `observed_effort_score` on a relative 0–10 scale, with
`easy`, `medium`, `hard`, and `very_hard` observed-effort labels separated at
each model's 25th, 50th, and 75th percentiles.
Per-instance summaries average repeated rollouts while preserving the complete
per-rollout measurements. Oracle
match is not part of any raw component or score; it is joined afterward from
`validation_report.json` so successful and unsuccessful effort can be compared.
If `complexity_report.json` is available, the report also groups effort by
intrinsic difficulty, category, and answer archetype.

```bash
python3 -m repogen rollout-effort --all-runs --output-root out \
  --agent claude-code --complexity-report out/complexity_report.json
```

The detailed output is written to `rollout_effort_report.json`.

For a solvability-filtered, instance-level downstream analysis, retain only
rollouts whose answers matched the validation oracle, normalize within each
validator model, average all retained rollout scores per instance, and then
join the frozen averages to an evaluation scope:

```bash
python3 -m repogen rollout-effort --all-runs --output-root out \
  --agent claude-code --complexity-report out/complexity_report.json \
  --matched-only --aggregate-instances \
  --evaluation-scope kimi/kimi-k3 \
  --report out/matched_rollout_effort_report.json
```

The resulting `instances` array has one record per instance, including the
number of matched rollouts, models represented, average effort score and raw
metrics, effort difficulty, and downstream verdict. Mismatched and unknown
rollouts are excluded before normalization and averaging.

Repo → image mapping lives in `repositories.json` (same format as RepoBehave's
`Repositories.json`; override any image with `--image`).

Answer schemas are standardized: `repogen/prompts/canonical_templates.json`
holds the canonical `template_answer` shapes per category, extracted from the
manually verified RepoBehave benchmark. The generation prompt requires the
agent to use one of them verbatim (exact keys — `file`/`func`/`variable`
vocabulary, never invented alternatives); screening's `answer_rich` thresholds
are aligned with the smallest canonical template of each category.

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
4. **Collect and score**: the orchestrator copies the instance directory, harvest logs
   (`trace.log`, `pytest.log`, `oracle.log`), the prompt, the agent log and
   trajectory to the host, and appends a status record
   (`generated | agent_failed | no_oracle`) to `manifest.json` after every
   instance—the run is crash-safe—then refreshes intrinsic semantic reasoning,
   answer construction, repository navigation, and combined difficulty labels.

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

   By default `evaluate` only scores instances where **at least one Haiku or
   Fable rollout matched the oracle**. This is the canonical solvability gate
   and includes partial cascade passes. If neither model has a passing rollout,
   Kimi is not called. Pass `--all-instances` only when intentionally overriding
   this safeguard.

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
- **Screening rules are self-describing and fed to the generator.** Each
  `ScreeningRule` in `repogen/screening.py` has a `guidance(category)` method;
  `screening_contract(category)` assembles them into the `{{SCREENING_RULES}}`
  block of the generation prompt, so the agent is told the exact thresholds it
  must clear (which still run as the post-generation gate). One source of truth
  — editing a threshold updates both the check and the agent instructions.
- **Harness payload** (`repogen/payload/`): tracer, conftest, `qa_pipeline.sh`,
  scout — staged into each container verbatim.
- **Docker** (`docker_env.py`): a single `Container` facade; everything else is
  docker-agnostic.
