# M7_Invariants — runtime invariants over state

Ask which candidate properties over the target function's variables actually
held at every observation during the test run, AND how often each was
violated.

## Never answer with a bare boolean or a bare enum

A one-bit answer (`{"invariant_exists": true}`) is 50% correct by coin flip; a
four-way enum (`monotonicity`) is 25%. Neither measures whether the solver
simulated anything, and extra test methods do not make a boolean harder. Every
M7 answer MUST carry per-predicate counts, so the solver has to evaluate the
predicate at every observation and tally.

## Required question archetype

Violation accounting over the whole run — canonical template
`invariant_report`: a list of `{predicate, held_always, observations,
violations}` objects, one per candidate predicate stated in the question.

- State 3-6 candidate predicates VERBATIM in the question, each genuinely
  undecidable statically (its truth must depend on runtime data).
- `observations` = how many times the predicate was evaluated (one per
  execution of the stated observation point, summed across ALL test methods).
- `violations` = how many of those evaluations were false.
- `held_always` = `violations == 0`; it is redundant on purpose, so a solver
  that guesses the boolean still fails the counts.

Simpler shapes remain available ONLY for a single-predicate loop question:
`is_invariant_always_held`/`total_iterations_observed`/
`violating_iteration_count` — it already carries counts. Do not use a
standalone `invariant_exists` or `monotonicity` answer.

## Answer definition rules

- State each candidate predicate verbatim; predicates are evaluated on traced
  local values at the stated observation point.
- Define the observation point exactly (line + event), and say how many test
  methods contribute (all of them — counts are totals across the class).
- "Held" = true at every observation. A predicate with ZERO observations is
  not evaluable: state explicitly how to report it (e.g. `observations: 0`,
  `violations: 0`, `held_always: false`).
- Sort the list by `predicate` string ascending; state the tie-break.

## Hardness levers

- Mix predicates so some always hold, some are violated only on a late
  invocation, and at least one is violated exactly once — the counts then
  differ per predicate and cannot be guessed as a block.
- Aim for violation counts spanning a range (e.g. 0, 1, 7, 23) rather than
  all-zero or all-equal.
- Include one predicate that is never evaluated (its observation point is not
  reached), to punish assuming every predicate runs.
- Avoid predicates decidable from the source alone.
