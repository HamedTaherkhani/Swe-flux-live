# M6_InterProceduralCFG — call-graph dynamics (harder)

Like S6, but the answer must reconstruct a multi-function slice of the dynamic
call graph, not a single edge.

Good question archetypes (pick ONE):
- Dynamic reachability: which of the tracked functions executed at least once
  during the test — canonical template `covered_functions` (state sort order;
  include tracked functions chosen so some are NOT called).
- Dispatch resolution: for a dynamically dispatched call site (dict of
  handlers, getattr, overridden method), which concrete implementations ran,
  in order — canonical template `dispatched_implementations`.

Answer definition rules:
- Function identity = dotted qualname; give one example of the format. List
  the tracked function set explicitly in the question (it must match
  TRACE_FUNC coverage) — the solver cannot see TRACE_FUNC.
- State the inclusion rule precisely: direct calls from a listed function's
  frame vs any call while it is on the stack; how repeated calls, recursion,
  and generator resumptions are counted.
- Define ordering (preorder by call events / chronological) and counting.

Template: use a canonical template for this category (see the canonical
answer templates section) — `{file, func}` objects, never bare name strings.

Hardness levers:
- Prefer dispatch through data structures or inheritance, where the static
  call graph over-approximates badly.
- Involve >=4 distinct functions with non-uniform counts.
- Include one function that is defined but NOT called during the test
  (count 0) to punish static guessing.
