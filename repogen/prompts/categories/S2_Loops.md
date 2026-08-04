# S2_Loops — single-loop dynamic behavior

Ask about the runtime behavior of one specific loop in the target function.

Good question archetypes (pick ONE):
- Exact number of iterations of the loop at line L (define iteration = number
  of times the loop body's first line executes) for a stated invocation —
  canonical template 1 (`loop_iteration_count`).
- The value of a named loop variable at a specific iteration (e.g. the 3rd) —
  canonical template 2 (`nth_iteration`/`variable`/`value`).

Answer definition rules:
- Identify the loop by its header line number.
- Define iteration counting (1-based) and invocation counting explicitly.
- For template 2, state whether `value` is the raw number/string or a Python
  `repr` string, matching the declared type.

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Prefer `while` loops whose exit condition depends on computed state, or
  loops with `break`/`continue` — iteration counts are then not readable from
  the input size.
- Choose inputs so the iteration count is neither 0/1 nor equal to an obvious
  input length.
