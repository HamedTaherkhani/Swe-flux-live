# M7_Invariants — runtime invariants over state

Ask which candidate properties over the target function's variables actually
held at every observation during the test run.

Good question archetypes (pick ONE):
- Loop invariant check: given an explicit list of candidate predicates over
  named variables (e.g. `len(code) == length - 1`, `weighted_sum >= 0`,
  `i < len(items)`), report for each whether it held at EVERY execution of
  the loop-body's first line during the test (true/false per predicate).
- Relational invariants at return: for each invocation, which of the listed
  relations between parameters and return value held (e.g. `len(result) ==
  n`, `result.startswith(prefix)`); answer = the subset that held on ALL
  invocations vs those violated (with the first violating invocation index).
- Monotonicity/shape: whether a named variable was strictly increasing /
  non-decreasing / constant across loop iterations, per invocation.

Answer definition rules:
- List every candidate predicate verbatim in the question; predicates are
  evaluated on traced local values at the stated observation point.
- Define the observation point exactly (line + event), and "held" = true at
  every observation, with zero observations counting as NOT evaluable (say
  how to report that, e.g. "vacuous").

Template shape example:
```json
{"invariant_results": [{"predicate": "str", "held": "bool", "first_violation_invocation": "int"}]}
```

Hardness levers:
- Mix predicates so that some hold, some are violated only on a late
  invocation or iteration, and at least one is violated exactly once.
- 6–10 candidate predicates; avoid predicates decidable statically.
