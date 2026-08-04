# M5_Exceptions — layered exception behavior (harder)

Like S5, but must involve multiple exception events, re-raising, handler
interplay, or exception behavior across invocations.

Good question archetypes (pick ONE):
- Crash matrix over a multi-case test: which test cases crash (and with what
  exception type) vs complete safely — canonical template
  `crashing_tests`/`safe_tests`.
- The exception types observed during the whole run — canonical template
  `exception_types` (state sort order and dedup).

Answer definition rules:
- Exception type naming MUST use the same convention as S5, stated verbatim
  in the question: bare `type(exc).__name__` for built-ins (e.g. `ValueError`,
  never `builtins.ValueError`), `module.QualName` for all others. Message =
  exact `str(exc)`. The parser must emit exactly this convention.
- `test` values are pytest id strings; state the exact id format in the
  question with one example.
- State ordering (sorted by test id / chronological) explicitly.

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Same exception type raised at different lines and caught at different
  handlers is ideal.
- Include one invocation that succeeds and one that raises, so the matrix is
  not constant.

Testcase note — do not leak the answer into assertions (`answer_leak` rule):
the test must assert final outcomes to stay green, but never by naming the
exception types the question asks about. Use umbrella assertions
(`assertRaises(Exception)`) or record outcomes generically and assert derived
facts (e.g. how many sub-cases failed), and do not construct the raised
exceptions in the test with `side_effect=SomeError(...)` when `SomeError` is
part of the answer — trigger errors through the target's own code paths
instead.
