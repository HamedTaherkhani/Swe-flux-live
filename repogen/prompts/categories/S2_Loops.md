# S2_Loops — single-loop dynamic behavior

Ask about the runtime behavior of one specific loop in the target function.

Good question archetypes (pick ONE):
- Exact number of iterations of the loop at line L (define iteration = number
  of times the loop body's first line executes), per invocation.
- The value of a named loop variable at a specific iteration (e.g. the 3rd),
  or the sequence of values it takes.
- Whether/when the loop exits early via `break` and at which iteration.

Answer definition rules:
- Identify the loop by its header line number.
- Define iteration counting (1-based) and invocation counting explicitly.

Template shape example:
```json
{"loop_line": "int", "iterations_per_invocation": ["int"]}
```
or
```json
{"loop_variable_values": [{"iteration": "int", "value": "str"}]}
```

Hardness levers:
- Prefer `while` loops whose exit condition depends on computed state, or
  loops with `break`/`continue` — iteration counts are then not readable from
  the input size.
- Choose inputs so the iteration count is neither 0/1 nor equal to an obvious
  input length.
