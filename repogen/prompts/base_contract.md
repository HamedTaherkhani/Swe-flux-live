# RepoBehave Instance Generation Task

You are an expert benchmark engineer working inside a Docker container with the
repository checked out at `{{WORKDIR}}`. You will create exactly ONE new QA
instance that asks a precise question about the **runtime behavior** of a
specific function during a specific test run. The ground-truth answer is
harvested automatically by executing the test under a line-level tracer and
parsing the trace — never written by hand.

## Your assignment

- Repository: `{{REPO_KEY}}`
- Instance id (use exactly this): `{{INSTANCE_ID}}`
- Question category: `{{CATEGORY}}`
- Primary target function: `{{TARGET_QUALNAME}}` in `{{TARGET_FILE}}`
  (module `{{TARGET_MODULE}}`, lines {{TARGET_LINES}})
- Structural metrics of the target (from static analysis):
  {{TARGET_METRICS}}

Category-specific instructions:

{{CATEGORY_CARD}}

Instances already generated in this run (yours must NOT duplicate their
question style on the same function, and must not reuse their ids):
{{EXISTING_INSTANCES}}

## Fixed harness you must use (do not reinvent it)

The QA directory `{{QA_DIR}}` already contains:

- `shared/files/trace_plugin.py` — a `sys.settrace` tracer configured entirely
  by env vars: `TRACE_ON`, `TRACE_FILE` (substring of the target file path),
  `TRACE_FUNC` (comma-separated function-name suffixes), `TRACE_EVENTS`
  (subset of `call,line,return,exception`), `TRACE_OUT` (log path),
  `TRACE_LOG_ALL_LINES=1` to log every executed line. Each trace line looks
  like: `<timestamp> <abs_file>:<lineno> <module.qualname> event=<event>
  locals={...}` with `retval=` on returns and `exc=` on exceptions.
- `shared/files/conftest.py` — enables the tracer around each pytest test.
- `qa_pipeline.sh` — stages `shared/files/` and your instance `files/` into
  `{{WORKDIR}}`, then executes your `eval.sh`.

## Files you must create

Create the directory `{{QA_DIR}}/{{INSTANCE_ID}}/` with EXACTLY this layout:

```
{{QA_DIR}}/{{INSTANCE_ID}}/
├── eval.sh                 # tracer config + pytest + parser (see skeleton)
└── files/
    ├── testcase.py         # deterministic pytest test exercising the target
    └── parser.py           # trace -> oracle.json (question + answer)
```

`eval.sh` MUST follow this skeleton (adapt the ALL-CAPS parts only):

```bash
#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-{{WORKDIR}}}"
INSTANCE_ID="{{INSTANCE_ID}}"
TEST_ID="{{QA_DIR_NAME}}/{{INSTANCE_ID}}/files/testcase.py::TESTCLASS::TESTMETHOD"
LOG_DIR="$ROOT_DIR/logs/{{QA_DIR_NAME}}/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="RELATIVE/PATH/TO/TARGET_FILE.py"
export TRACE_FUNC="TARGET_FUNC_NAME"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python {{QA_DIR_NAME}}/{{INSTANCE_ID}}/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/{{QA_DIR_NAME}}/{{INSTANCE_ID}}/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
```

`parser.py` requirements:

- Reads the trace log (and, if needed, the target source via `ast`) and
  computes the answer purely deterministically. No randomness, no timestamps,
  no dict-ordering dependence (sort everything you emit).
- MUST fail loudly (non-zero exit, clear message) if the trace log is missing,
  empty, or contains zero events for the target function. Never emit a
  plausible-looking empty answer from an empty trace.
- Writes `oracle.json` with EXACTLY these top-level keys:
  - `question_kind`: `"{{CATEGORY}}"`
  - `question`: the full question text (see checklist below)
  - `template_answer`: a JSON skeleton mirroring the exact structure of
    `oracle_answer`, with type-name strings (`"str"`, `"int"`, ...) as values
  - `oracle_answer`: the computed ground truth

## The generation process you must follow, in order

1. **Study the target.** Read `{{TARGET_FILE}}` around lines {{TARGET_LINES}}
   and its callers/callees. Understand every branch, loop, and exception path
   and what inputs steer them.
2. **Design the scenario.** Choose concrete, seeded, deterministic inputs that
   drive the target through NON-TRIVIAL behavior for this category (see the
   category card's hardness levers). Prefer inputs that execute multiple
   branches/iterations and would surprise someone who only skims the code.
3. **Write `files/testcase.py`.** A `unittest.TestCase` runnable by pytest.
   It must be fully deterministic: seed every RNG, freeze anything
   time-dependent, avoid network/filesystem randomness. Keep it minimal but
   assert enough that a broken environment fails the test. Do NOT modify any
   repository source file.
4. **Write `eval.sh`** from the skeleton. Verify `TRACE_FILE`/`TRACE_FUNC`
   actually match the target (beware same-named functions in other files).
5. **Write `files/parser.py`** implementing exactly the category's answer
   definition from the category card.
6. **Run the pipeline end to end:**
   `bash {{QA_DIR}}/qa_pipeline.sh {{INSTANCE_ID}} {{WORKDIR}}`
   Debug until it exits 0 and writes the oracle.
7. **Inspect the oracle critically.**
   - The answer must be non-trivial: not empty, not a single obvious value.
     If it is trivial, go back to step 2 and choose harder inputs.
   - Re-run step 6 a second time and confirm `oracle.json` is byte-identical.
     If not, remove the nondeterminism and repeat.
8. **Audit the question text** against this checklist — every item must hold:
   - names the exact test file path, test class, and test method;
   - names the exact target function qualname and file path;
   - defines every term of art it uses (e.g. what counts as an "iteration",
     a "use", a "call") precisely enough that two experts would compute the
     same answer;
   - states the exact output keys, their types, and the sort order plus
     tie-breaking rules;
   - is answerable from the question + repository + test alone (never
     references the parser, the tracer, env vars, or this prompt);
   - contains no hints that reveal the answer.
9. **Finalize.** Ensure the instance directory contains exactly `eval.sh`,
   `files/testcase.py`, `files/parser.py`, and the synced `oracle.json`.

## Screening rules — your instance MUST pass ALL of these

After you finish, an automated screener re-checks this instance and DISCARDS it
if any rule below fails. Design the test scenario, parser, and question up front
so every rule passes. The thresholds are specific to `{{CATEGORY}}`:

{{SCREENING_RULES}}

If you cannot make the target clear these thresholds with a reasonable scenario,
prefer choosing richer inputs (bigger loops, more branches, more state changes)
over settling for a thin instance.

## Hard constraints

- Never modify repository source files, `shared/`, or `qa_pipeline.sh`.
- Never hardcode the oracle answer in the parser; it must be derived from the
  trace at parse time.
- The whole run must be reproducible: same container, same command, same
  oracle bytes.
- Work only inside `{{WORKDIR}}`. Do not ask for confirmation; finish the job.
