# M6_InterProceduralCFG — call-graph dynamics (harder)

Like S6, but the answer must reconstruct a multi-function slice of the dynamic
call graph, not a single edge — and it must report HOW MANY TIMES each function
ran, not merely whether it ran.

## Do not enumerate the candidate functions

NEVER list the individual functions to be answered about in the question. A
list of candidates turns the task into a yes/no vote per line, which a solver
can win by answering "all of them" — measured at ~100% solve rate, i.e. the
question stopped discriminating.

Instead, define the tracked set by LOCATION, and make the solver discover its
members:

> "Consider every function and method defined in `<pkg/mod.py>` (all
>  module-level functions and all methods of class `X`)."

The scope you name must exactly match TRACE_FUNC coverage. Name a file, a
module, or a class — never the member names themselves. The solver has to read
the file to find the members, then work out which ones actually ran.

## Required question archetype

Per-function invocation counts over the located scope — canonical template
`invocation_counts`, a list of `{file, func, count}` objects.

The answer MUST include every function in the named scope, including ones that
never ran (`count: 0`). That is what forces the solver to enumerate the scope
itself rather than only report what it noticed.

Alternative (use only if the target has a genuine dynamic dispatch site):
- Dispatch resolution: which concrete implementations a dynamically dispatched
  call site selected, in order — canonical template
  `dispatched_implementations`. Order matters, so it stays discriminating.

## Answer definition rules

The question must be unambiguous on its own. State ALL of:

- **Scope**: the exact file/module/class whose functions are tracked, and
  whether nested functions, closures, comprehensions, properties, `__init__`,
  dunder methods, and inherited methods are included or excluded.
- **Identity**: function identity = dotted qualname, with one worked example
  of the exact format (e.g. `pkg.mod.Class.method`).
- **What counts as one invocation**: one Python `call` event for that
  function's frame — including calls made transitively, recursively, or from
  any frame; and state explicitly whether a generator/coroutine resumption
  emits another `call` event and therefore counts again.
- **Zero rule**: functions in scope that never execute appear with `count: 0`.
- **Aggregation**: counts are summed across ALL test methods in the test class
  (this category requires many), not per method.
- **Sort order**: sort by `func` ascending (state the tie-break if two entries
  can share a qualname).

## Hardness levers

- Prefer dispatch through data structures or inheritance, where the static call
  graph over-approximates badly — the counts then cannot be read off the source.
- Aim for >= 6 functions in scope with NON-UNIFORM counts spanning at least an
  order of magnitude (e.g. 1, 3, 12, 47, 0) so no single guess fits.
- Ensure at least one in-scope function has `count: 0` and at least one has a
  count in the double digits.
- Drive the counts from data-dependent branching across the test methods, so
  the totals cannot be derived by multiplying one method's behavior.
