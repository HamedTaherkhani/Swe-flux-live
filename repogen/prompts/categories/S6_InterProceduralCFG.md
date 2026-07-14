# S6_InterProceduralCFG — calls between functions

Ask about the dynamic call structure around the target function during the
test run.

Good question archetypes (pick ONE):
- The exact ordered sequence of same-module functions the target calls during
  its k-th invocation (trace multiple functions via TRACE_FUNC list).
- How many times the target function itself is invoked during the test, and
  from which caller functions (qualified names).
- The maximum call depth reached within a named call chain (define depth
  counting precisely).

Answer definition rules:
- Function identity = dotted qualname as `module.Class.method` /
  `module.function`; state this format in the question.
- Define call ordering by `call` trace events; state which invocation.

Template shape example:
```json
{"callee_sequence": ["str"]}
```
or
```json
{"invocation_count": "int", "callers": ["str"]}
```

Hardness levers:
- Prefer targets whose callees are chosen dynamically (dispatch dicts,
  getattr, polymorphism) so the sequence isn't readable statically.
- Choose inputs where the callee sequence differs between invocations and ask
  about a specific one.
- Configure TRACE_FUNC with every function name involved, and verify the
  trace captures all of them before parsing.
