# M2_Loops — multi-loop / nested-loop dynamics (harder)

Like S2, but must involve multiple loops, nested loops, or loop behavior
across multiple invocations, combined into one answer.

Good question archetypes (pick ONE):
- For every loop in the function (identified by header line), total iteration
  count during the whole test plus per-invocation breakdown.
- For a nested loop, the iteration count of the inner loop for EACH iteration
  of the outer loop (a list of lists or list of {outer_iteration, inner_count}).
- Early-exit map: for each invocation, whether each loop exited via condition,
  `break`, or exception, and at which iteration.

Answer definition rules:
- Identify each loop by header line number; define iteration = executions of
  the body's first line; 1-based counting; state invocation ordering.

Template shape example:
```json
{"inner_iterations_per_outer": [{"outer_iteration": "int", "inner_iterations": "int"}]}
```

Hardness levers:
- Nested loops where the inner bound depends on outer state are ideal.
- `while` loops with data-dependent exits beat `for` loops over fixed ranges.
- Ensure at least ~6 distinct counts appear in the answer so it cannot be
  guessed from one observation.
