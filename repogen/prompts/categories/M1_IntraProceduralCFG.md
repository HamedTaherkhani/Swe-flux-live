# M1_IntraProceduralCFG — multi-aspect control flow (harder)

Like S1, but the question must combine MULTIPLE control-flow aspects of the
target function in one answer, requiring the solver to reconstruct how often
each part of the function ran — not merely whether it ran.

## Never answer with a bare coverage union

`covered_lines` — the set of lines executed at least once — degenerates in this
category. Across the 10-15 test methods M1 requires, the union saturates toward
"every line of the function", so the answer becomes derivable from the source
alone without simulating anything. Report per-line COUNTS instead.

## Required question archetype

Per-line execution counts across the whole test — canonical template
`line_execution_counts`, a list of `{line, count}` objects.

- Scope = every line of the target function's body (state the line range in
  the question, or define it as "all lines of the function as defined at
  `file:line`").
- Lines that never execute MUST appear with `count: 0`. That is what stops the
  answer from being read off the source.
- Counts are TOTALS summed across all invocations in all test methods.

## Answer definition rules

- Define "executed line" via runtime line events; state whether the `def` line
  and decorator lines count, and the multi-line-statement convention (which
  physical line the event fires on).
- State that counts aggregate over ALL test methods in the class.
- State the treatment of lines that are blank, comments, or continuations —
  either excluded from scope or reported with `count: 0`, but say which.
- Sort by `line` ascending.

## Hardness levers

- Prefer functions with >= 4 branches and early returns, so different methods
  take genuinely different paths and the counts differ per line.
- Drive loops inside the function so some lines have counts far above the
  number of invocations (e.g. 1, 4, 37) — a solver must then simulate the
  loops, not just count calls.
- Ensure at least one line in scope has `count: 0` (a branch no method takes)
  and at least one has a double-digit count.
- Vary inputs so the per-line profile of one method does not predict another's.
