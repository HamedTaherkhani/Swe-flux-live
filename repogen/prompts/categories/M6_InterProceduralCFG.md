# M6_InterProceduralCFG — call-graph dynamics (harder)

Like S6, but the answer must reconstruct a multi-function slice of the dynamic
call graph, not a single edge.

Good question archetypes (pick ONE):
- Dynamic call tree: for the target's k-th invocation, the nested tree (or
  indented preorder list) of traced same-module calls with per-callee counts.
- Call-frequency table: for a named set of functions, how many times each was
  invoked during the whole test, plus the first caller of each.
- Dispatch resolution: for a dynamically dispatched call site (dict of
  handlers, getattr, overridden method), which concrete function ran for each
  of a series of inputs, in order.

Answer definition rules:
- Function identity = dotted qualname; define the traced function set in the
  question (it must match TRACE_FUNC coverage).
- Define ordering (preorder by call events / chronological) and counting.

Template shape example:
```json
{"call_frequencies": [{"function": "str", "count": "int", "first_caller": "str"}]}
```

Hardness levers:
- Prefer dispatch through data structures or inheritance, where the static
  call graph over-approximates badly.
- Involve >=4 distinct functions with non-uniform counts.
- Include one function that is defined but NOT called during the test
  (count 0) to punish static guessing.
