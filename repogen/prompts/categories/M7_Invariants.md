# M7_Invariants — runtime invariants over state

Ask which candidate properties over the target function's variables actually
held at every observation during the test run.

Good question archetypes (pick ONE):
- Single-predicate invariant check: state ONE candidate predicate verbatim in
  the question (e.g. `len(code) == length - 1` at every execution of line L)
  and ask whether it held at every observation — canonical template
  `invariant_exists`. Pick a predicate that is genuinely hard to decide
  statically (its truth must depend on the runtime data).
- Loop invariant with violation accounting: one predicate checked at every
  iteration, reporting whether it always held, how many iterations were
  observed, and how many violated it — canonical template
  `is_invariant_always_held`/`total_iterations_observed`/
  `violating_iteration_count`.
- Monotonicity/shape: whether a named variable was `strictly_increasing`,
  `non_decreasing`, `constant`, or `none` across loop iterations — canonical
  template `monotonicity` (enumerate the allowed strings verbatim in the
  question).

Answer definition rules:
- State the candidate predicate verbatim in the question; predicates are
  evaluated on traced local values at the stated observation point.
- Define the observation point exactly (line + event), and "held" = true at
  every observation, with zero observations counting as NOT evaluable (say
  how to report that).

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Mix predicates so that some hold, some are violated only on a late
  invocation or iteration, and at least one is violated exactly once.
- 6–10 candidate predicates; avoid predicates decidable statically.
