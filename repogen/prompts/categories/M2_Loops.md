# M2_Loops — multi-loop / nested-loop dynamics (harder)

Like S2, but must involve multiple loops, nested loops, or loop behavior
across multiple invocations, combined into one answer.

Good question archetypes (pick ONE):
- Max and min iteration counts of a stated loop across all invocations during
  the test — canonical template `max_iterations`/`min_iterations`.
- Total iterations of a stated loop summed over the whole test — canonical
  template `total_iterations`.
- Which test cases exit the loop via `break` — canonical template
  `tests_terminating_at_break` (pytest id strings, sorted; requires a
  multi-case test).

Answer definition rules:
- Identify each loop by header line number; define iteration = executions of
  the body's first line; 1-based counting; state invocation ordering.

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Nested loops where the inner bound depends on outer state are ideal.
- `while` loops with data-dependent exits beat `for` loops over fixed ranges.
- Ensure at least ~6 distinct counts appear in the answer so it cannot be
  guessed from one observation.
