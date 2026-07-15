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

- Python 3.9+ on the host (stdlib only — nothing to pip install)
- Docker
- For `--agent cursor`: `cursor-agent` installed on the host
  (https://cursor.com/docs/cli/installation) and `CURSOR_API_KEY` set.

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

Validation/repair/certification gates are deliberately out of scope here; this
project only guarantees a well-structured, reproducible *generation* process.

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
└── logs/<id>/             # prompt.md, agent log + traj, harvest/ logs
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
  `--agent` automatically. `cursor` is implemented; `codex` and `claude-code`
  are registered placeholders.
- **Categories** (`repogen/prompts/categories/*.md` + `planner.CATEGORY_PROFILES`):
  adding a category = one markdown card + one `CategoryProfile`
  (eligibility + affinity).
- **Prompt contract** (`repogen/prompts/base_contract.md`): edit without
  touching code; `{{TOKEN}}` substitution only.
- **Harness payload** (`repogen/payload/`): tracer, conftest, `qa_pipeline.sh`,
  scout — staged into each container verbatim.
- **Docker** (`docker_env.py`): a single `Container` facade; everything else is
  docker-agnostic.
