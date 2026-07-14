# M1_IntraProceduralCFG — multi-aspect control flow (harder)

Like S1, but the question must combine MULTIPLE control-flow aspects of the
target function in one answer, requiring the solver to reconstruct the full
path, not just one fact.

Good question archetypes (pick ONE):
- Per-invocation branch report: for EVERY `if`/`elif` in the function and
  EVERY invocation during the test, whether the branch was taken — plus the
  count of invocations.
- Executed-lines fingerprint: for each invocation, the ordered list of
  executed line numbers, for at least 3 invocations with differing paths.
- Combined reachability: lines executed in some invocation but not all,
  lines executed in all invocations, lines never executed (three lists).

Answer definition rules:
- Define invocation counting and "executed line" via runtime events.
- Sort every list ascending; state tie-breaks.

Template shape example:
```json
{"always_executed": ["int"], "sometimes_executed": ["int"], "never_executed": ["int"]}
```

Hardness levers:
- The test MUST drive the function through at least 3 invocations with
  distinct paths (different inputs/branches).
- Prefer functions with >=4 branches and early returns.
- The three lists (or per-invocation reports) must each be non-empty.
