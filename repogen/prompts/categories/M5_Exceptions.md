# M5_Exceptions — layered exception behavior (harder)

Like S5, but must involve multiple exception events, re-raising, handler
interplay, and exception behavior aggregated across many invocations.

## Do not ask for a bare set of exception types

NEVER make the answer a deduplicated list of exception type names. Python's
common builtins are a short, familiar universe and each failing idiom
(`1/0`, `{}[k]`, `bytes([255]).decode("ascii")`) is recognised on sight, so
dedup collapses a large run into ~7 guessable strings — measured at ~83% solve
rate, i.e. the question barely discriminates. Dedup also throws away exactly
the volume this category is supposed to test.

Keep the multiplicity in the answer: report per-type COUNTS, or attribute each
outcome to the test method that produced it.

## Required question archetypes (pick ONE)

- **Per-type observation counts** — how many times each exception type was
  observed in the target frame across the whole run. Canonical template
  `exception_type_counts`, a list of `{exception_type, count}` objects.
  Every type observed at least once appears; counts are totals, not distinct
  invocations. This is the default choice.

- **Crash matrix** — for each test method, whether it crashed and with what
  exception type, versus completing safely. Canonical template
  `crashing_tests`/`safe_tests`, keyed by pytest id. This category requires
  10-15 test methods, so the matrix is genuinely wide; use it when the
  interesting variation is *which scenario* fails rather than how often.

## Answer definition rules

The question must be unambiguous on its own. State ALL of:

- **Naming**: exception type naming MUST use the same convention as S5, stated
  verbatim: bare `type(exc).__name__` for built-ins (e.g. `ValueError`, never
  `builtins.ValueError`), `module.QualName` for all others. Message = exact
  `str(exc)`. The parser must emit exactly this convention.
- **Observation rule**: what counts as observing an exception in the target
  frame — raised by code in that exact frame, or propagated in from a callee;
  counted once per target-frame observation; exceptions raised AND fully
  handled inside a callee do not count. Say whether a re-raise of the same
  exception object in the same frame counts again.
- **Counting** (counts archetype): counts are totals over ALL invocations and
  ALL test methods, so the same type raised in five methods contributes five.
- **Pytest ids** (matrix archetype): give the exact id format with one example.
- **Sort order**: for counts, sort by `exception_type` ascending; state the
  tie-break. For the matrix, sort by test id.

## Hardness levers

- Same exception type raised at different lines, through different handlers,
  in different methods — so the count cannot be inferred from one code path.
- Aim for NON-UNIFORM counts spanning a wide range (e.g. 1, 2, 9, 23) rather
  than every type appearing once, which degenerates back into a set.
- Include a type that is observed only via propagation from a callee, and a
  handler that swallows a different type entirely (so it never appears).
- Include at least one test method that completes with no exception at all.

Testcase note — do not leak the answer into assertions (`answer_leak` rule):
the test must assert final outcomes to stay green, but never by naming the
exception types the question asks about. Use umbrella assertions
(`assertRaises(Exception)`) or record outcomes generically and assert derived
facts (e.g. how many sub-cases failed), and do not construct the raised
exceptions in the test with `side_effect=SomeError(...)` when `SomeError` is
part of the answer — trigger errors through the target's own code paths
instead.
