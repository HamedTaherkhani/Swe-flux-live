# M3_ProgramState — multi-variable / multi-point state (harder)

Like S3, but the answer must combine state observations across MULTIPLE
variables AND multiple program points or invocations.

Good question archetypes (pick ONE):
- Extrema of a traced numeric variable across the whole test (all
  invocations) — canonical template `min_value`/`max_value` (optionally with
  `variable`).
- The sorted set of distinct repr values a variable takes during the run —
  canonical template `unique_values`.

Answer definition rules:
- Values in `unique_values` are Python `repr` strings; numeric extrema are
  raw numbers matching the declared type. Say which in the question.
- Define the observation scope exactly (which lines/events, which
  invocations) and the sort order (ascending; state the string sort rule).

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Track COMPUTED values (extrema of an accumulator, distinct derived states)
  — never copies of test inputs, or the answer is readable off the test file
  (`answer_leak`).
- Choose variables mutated in interleaved branches/loops, so the timeline
  requires precise path tracking.
- Include at least one variable holding a container that is mutated in place.
- Answer should contain >=8 entries.
