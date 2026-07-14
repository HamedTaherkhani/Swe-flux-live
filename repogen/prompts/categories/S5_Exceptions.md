# S5_Exceptions — exception raising, propagation, handling

Ask about the concrete exception behavior of the target function during the
test run.

Good question archetypes (pick ONE):
- The exact exception type and message raised at line L, and whether it
  propagated out of the function or was handled (and at which handler line).
- The ordered sequence of `exception` events (line, exception type) observed
  in the function during the test.
- Given inputs that make an error path reachable, which line raises first and
  what the final observable outcome of the call is (define "observable
  outcome": return value repr, or exception type propagated to the caller).

Answer definition rules:
- Exception identity = fully qualified type name plus exact `str(exc)` message
  (say both are required).
- Distinguish "raised", "caught at line H", "propagated out".

Template shape example:
```json
{"exception_events": [{"line": "int", "exception_type": "str", "message": "str", "handled": "bool"}]}
```

Hardness levers:
- Prefer functions where the same exception type can arise from multiple
  lines, so the line number matters.
- Drive an input through a try/except/finally so handled vs propagated is not
  guessable from the signature.
- Testcase note: if the call is expected to raise out of the target, the test
  should assert it (e.g. `assertRaises`) so the test still passes.
