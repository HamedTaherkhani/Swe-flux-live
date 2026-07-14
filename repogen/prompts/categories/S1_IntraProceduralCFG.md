# S1_IntraProceduralCFG — single-function control flow

Ask about the concrete control-flow path taken through the target function
during the test run.

Good question archetypes (pick ONE):
- The exact ordered sequence of executed line numbers inside the function for
  its k-th invocation (state which invocation and how invocations are counted).
- For each `if`/`elif` line in the function, whether its condition evaluated
  and which branch (then/else) was taken, per invocation.
- The set of executable lines of the function that were NEVER executed during
  the test (define "executable line" precisely, e.g. lines with trace events).

Answer definition rules:
- Line numbers refer to the target file on disk in this container.
- Define invocation counting (1-based, order of `call` events for this
  function during the test).

Template shape example:
```json
{"executed_line_sequence": ["int"]}
```
or
```json
{"branch_outcomes": [{"line": "int", "invocation": "int", "taken": "str"}]}
```

Hardness levers:
- Choose inputs so the path differs between invocations, then ask about a
  middle invocation (not first/last).
- Prefer functions where early returns / guard clauses make the static path
  non-obvious.
- The answer sequence should have at least ~10 elements or cover >=3 branches.
