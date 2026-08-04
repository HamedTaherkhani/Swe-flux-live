# M1_IntraProceduralCFG — multi-aspect control flow (harder)

Like S1, but the question must combine MULTIPLE control-flow aspects of the
target function in one answer, requiring the solver to reconstruct the full
path, not just one fact.

Good question archetypes (pick ONE):
- Line coverage of the target across the WHOLE test (multiple invocations
  with differing paths): the sorted set of the function's line numbers that
  executed at least once — canonical template `covered_lines`.
- The same, but with the test driving >=3 invocations through distinct
  branches, so the union is not derivable from any single invocation.

Answer definition rules:
- Define "executed line" via runtime line events; state whether the `def`
  line counts and the multi-line-statement convention.
- `covered_lines` is sorted ascending, deduplicated; say so in the question.

Template: use THE canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- The test MUST drive the function through at least 3 invocations with
  distinct paths (different inputs/branches).
- Prefer functions with >=4 branches and early returns.
- The three lists (or per-invocation reports) must each be non-empty.
