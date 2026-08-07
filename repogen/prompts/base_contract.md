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
- Known same-module callers of the target: {{TARGET_CALLERS}}

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

## Canonical answer templates — MANDATORY

`template_answer` (and therefore the shape of `oracle_answer`) must be one of
the canonical templates below, copied EXACTLY — same keys, same nesting, same
spelling. These shapes come from the manually verified RepoBehave benchmark;
consistency across instances is a hard requirement. Never invent new keys,
never rename keys (`file` never becomes `file_path`, `variable` never becomes
`var`), never add or drop fields. Only the deviations listed under "what may
vary" are allowed. If a category card's archetype seems to suggest a different
shape, the canonical template wins — pick the archetype that fits one of these
templates.

Canonical templates for `{{CATEGORY}}`:

{{CANONICAL_TEMPLATES}}

Key conventions everywhere: `file` = repo-relative path
(e.g. `haystack/core/pipeline/base.py`); `func` = dotted `module.qualname`
(e.g. `haystack.core.pipeline.base.PipelineBase.connect`); tests are referenced
by pytest id strings.

## The solvability contract — the bar every instance must clear

The finished instance is judged by one test: **a very strong engineer (or
LLM), given ONLY the question text, the instance test files, and the
repository — with the ability to run the test and add their own
instrumentation, but with NO access to your parser, the tracer, or this
prompt — must be able to produce an answer that is byte-for-byte identical to
`oracle_answer`.** Scoring is exact string/number comparison. If any leaf
value could plausibly be written two different ways by such a solver, the
question is ambiguous and the instance is broken, no matter how correct the
oracle is.

That means the question must pin down BOTH the semantics and the exact
serialization of every value. The following conventions have caused real
solver mismatches; whenever one applies to your answer, the question MUST
state the rule explicitly (with a short inline example that is NOT taken from
the answer):

- **Exception type names.** Pick one convention and say it: bare
  `type(exc).__name__` for built-in exceptions (`ValueError`, never
  `builtins.ValueError`) and `module.QualName` for non-builtins — or another
  rule, but stated. The parser must emit exactly the same convention.
- **Function/callee names.** State the exact format (`module.Class.method`
  vs `Class.method` vs bare name) and give one example.
- **Which calls/events count.** For call sequences: only direct calls made by
  the target's own frame, or transitive ones? Are calls to functions outside
  the traced set, builtins, comprehension frames, or generator resumptions
  included? State the inclusion rule; do not leave it to the trace
  configuration, which the solver cannot see.
- **Value formatting.** State `repr()` vs `str()` for every reported value;
  for containers, state Python `repr` of the whole container. Mind JSON vs
  Python spellings (`null`/`true` vs `None`/`True`) — say which appears
  inside strings. Empty string `""`, JSON `null`, and an absent key are three
  different answers; state which one represents "no value".
- **Line numbers.** Absolute, 1-based, in the named file as it exists in the
  repo. For multi-line statements, the executed-line event fires on the line
  where that statement/expression begins — state this when sequences may
  include multi-line calls. State whether the `def` line, decorator lines, or
  docstring lines can appear.
- **Counting.** Invocation = one `call` of the function during the test run,
  1-based, in chronological order — restate this in the question. Iteration
  counting: define it (e.g. "iteration N = the Nth time the loop body's first
  line executes"). 
- **Ordering and dedup.** Give a total order (every tie-breaker, ascending/
  descending) and state whether and when duplicates are removed.
- **Def/use subtleties.** Augmented assignment (`x += 1`) reads then writes —
  state whether it is a use, a def, or both. State how comprehension-local
  variables and parameters are treated.

If pinning a convention down makes the question longer — good. Length is
cheap; ambiguity is fatal.

## Leave no trace of the answer — and make it computed, not copied

The solver sees the question text and `files/testcase.py`. **No distinctive
value of `oracle_answer` may appear literally in either.** This is enforced by
the `answer_leak` screening rule below; instances that fail it are discarded.
The common leaks, and how to avoid them:

- **Test assertions that spell out the answer.** If the question asks for the
  exception type/message, `self.assertRaises(ValueError)` and
  `assertRaisesRegex(..., "<the full message>")` hand the solver the answer.
  Assert *around* the answer instead: use `assertRaisesRegex` with a short
  partial pattern that is NOT the substring the question asks about, assert a
  derived property (`len`, type of a field, a checksum-style relation), or
  prefer scenarios where the target CATCHES the exception internally so the
  test only asserts the normal return value.
- **Inputs that equal outputs.** If the answer can be found by copying a
  literal from the test's inputs (a list length, a string passed in, a
  constant from the source), the instance is trivial for a static reader.
  Prefer answers that are **computed by the runtime**: accumulated counts,
  transformed/merged state, orders of traversal, values that emerge from
  branch interplay. Rule of thumb: if `grep` over the test + target source
  can produce the answer value, choose different inputs or a different
  question; if reproducing the value requires actually simulating the
  execution, it is a good answer.
- **Question text that restates answer values.** Name variables, lines, and
  conventions — never example values that occur in the answer.

After harvesting the oracle, grep every distinctive leaf of `oracle_answer`
against your question text and `files/testcase.py`. Any hit (outside the
structurally required enumerations noted in the screening rule) means:
redesign the assertion or the scenario and re-run.

## How to reach the target: {{EXERCISE_MODE}}

{{EXERCISE_DIRECTIVE}}

## Make the runtime too big to simulate in the head

A static reader with the test and the source will try to "run" the code
mentally. Defeat that with volume and data dependence, not obscurity:

- Drive loops through **15+ iterations** whose behavior differs per iteration
  (data-dependent branches, accumulators), not 2–3 token passes. The
  trace_rich thresholds below are floors, not targets — exceed them.
- Build test inputs **programmatically** (seeded generators, comprehensions
  producing dozens of elements, values derived from prior computation) so the
  solver must simulate the construction too — never small literal lists.
- Where the canonical template is a list, prefer answers with **many
  elements** (long exact sequences punish drift: one slip anywhere is wrong).
- Prefer behavior that emerges from branch interplay across iterations or
  recursion depth over anything readable from a single pass.

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
   - states the exact serialization of every value, per the solvability
     contract's convention list (exception names, repr vs str, empty vs null,
     name formats, line-number conventions);
   - is answerable from the question + repository + test alone (never
     references the parser, the tracer, env vars, or this prompt);
   - contains no hints that reveal the answer.
9. **Question ↔ parser consistency audit.** Re-read your `parser.py` and list
   every transformation it applies between the raw trace and the emitted
   answer: filtering (which events/frames are dropped), normalization (name or
   type-string rewriting, message truncation), sorting, dedup, formatting.
   For EACH transformation, point to the sentence in the question that states
   the same rule. If the parser does something the question does not say, fix
   one of them until they match — usually by stating the rule in the question.
   Then walk every leaf value of `oracle_answer` and ask: "could a competent
   solver, obeying the question exactly, have written this value differently
   (extra module prefix, str instead of repr, 0-based index, unsorted,
   un-deduped)?" If yes for any value, revise the question and re-run step 6.
10. **Finalize.** Ensure the instance directory contains exactly `eval.sh`,
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
