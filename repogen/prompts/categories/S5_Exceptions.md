# S5_Exceptions — exception raising, propagation, handling

Ask about the concrete exception behavior of the target function during the
test run.

Good question archetypes (pick ONE):
- The exact exception type and message that reaches the caller (or is raised
  at a stated point) for inputs driving an error path — canonical template 1
  (`exception_type`/`exception_message`).
- The set of exception types caught inside the function during the run —
  canonical template 2 (`caught_exception_kinds`; state sort order).

Answer definition rules:
- Exception type naming MUST use this convention, stated verbatim in the
  question: bare `type(exc).__name__` for built-in exceptions (e.g.
  `ValueError` — never `builtins.ValueError`), and `module.QualName` for all
  others (e.g. `haystack.core.errors.PipelineError`). The parser must emit
  exactly this convention.
- Message = exact `str(exc)`, character for character; say so in the question.
- Distinguish "raised", "caught at line H", "propagated out".

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Prefer functions where the same exception type can arise from multiple
  lines, so the line number matters.
- Drive an input through a try/except/finally so handled vs propagated is not
  guessable from the signature.
- STRONGLY prefer the caught-exceptions archetype (template 2) with a target
  that handles errors internally: the test then only asserts the normal
  return value, so nothing about the exceptions appears in the test file.

Testcase note — do not leak the answer into assertions (`answer_leak` rule):
if the call must raise out of the target, the test has to assert the raise to
stay green, but assert it WITHOUT naming what the question asks for. If the
question asks for the message, use `assertRaises(Type)` alone or
`assertRaisesRegex` with a short pattern disjoint from the reported message.
If the question asks for the type, the type must not be spelled in the test —
catch broadly (`except Exception` bookkeeping in the test, or
`assertRaises(BaseException)`-style umbrella) or redesign toward template 2.
