# M5_Exceptions — layered exception behavior (harder)

Like S5, but must involve multiple exception events, re-raising, handler
interplay, or exception behavior across invocations.

Good question archetypes (pick ONE):
- Full exception timeline of the test for the target (and optionally its
  callees): ordered events `(function, line, exception_type, handled_where)`.
- Raise/handle matrix across invocations: for each invocation, whether an
  exception occurred, its type/message, and whether the caller saw it.
- try/except/finally choreography: the exact executed line sequence through a
  try block including handler and finally lines, for an erroring input AND a
  clean input (two sequences).

Answer definition rules:
- Exception identity = qualified type + exact message; "handled_where" is a
  handler line number or the string "propagated".
- Chronological ordering by trace events; state it.

Template shape example:
```json
{"exception_timeline": [{"function": "str", "line": "int", "exception_type": "str", "handled_where": "str"}]}
```

Hardness levers:
- Same exception type raised at different lines and caught at different
  handlers is ideal.
- Include one invocation that succeeds and one that raises, so the matrix is
  not constant.
- The test must assert the final outcome (including expected propagation).
