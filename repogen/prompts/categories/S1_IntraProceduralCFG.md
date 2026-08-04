# S1_IntraProceduralCFG — single-function control flow

Ask about the concrete control-flow path taken through the target function
during the test run.

Good question archetypes (pick ONE):
- The exact ordered sequence of executed line events inside the function for
  its k-th invocation (state which invocation and how invocations are
  counted) — canonical template 1 (`executed_path`).
- The same, but for an invocation chosen so that guard clauses / early
  returns / rare branches make the path non-obvious.

Answer definition rules:
- Use canonical template 1: `executed_path` objects `{file, func, line}` —
  `file` is the repo-relative path, `func` the dotted module.qualname, both
  identical in every element (it is still required per element).
- Line numbers refer to the target file on disk in this container.
- Define invocation counting (1-based, order of `call` events for this
  function during the test).
- State whether the `def` line appears in the sequence, and that a multi-line
  statement is reported as the line where the statement begins. If the
  function contains multi-line calls/conditions, say so explicitly in the
  question so the solver counts them the same way.

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Choose inputs so the path differs between invocations, then ask about a
  middle invocation (not first/last).
- Prefer functions where early returns / guard clauses make the static path
  non-obvious.
- The answer sequence should have at least ~10 elements or cover >=3 branches.
