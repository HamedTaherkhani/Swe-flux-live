# S6_InterProceduralCFG — calls between functions

Ask about the dynamic call structure around the target function during the
test run.

Good question archetypes (pick ONE):
- The exact ordered sequence of tracked same-module function calls during the
  target's k-th invocation — canonical template `function_call_order`.
- How many times a named function is invoked during the test — canonical
  template `function_call_count`.
- The maximum call depth reached within a named call chain (define depth
  counting precisely) — canonical template `maximum_call_stack_depth`.
- The cross-function executed line path — canonical template `executed_path`.

Answer definition rules:
- Function identity = dotted qualname as `module.Class.method` /
  `module.function`; state this format in the question WITH one example.
- Define call ordering by `call` trace events; state which invocation.
- State the inclusion rule for the sequence precisely — the solver cannot see
  TRACE_FUNC, so the question must carry it on its own: name the exact set of
  functions whose calls are counted (list them), and state whether only calls
  made directly from the target's frame count or also nested/transitive calls,
  and how repeated calls and generator resumptions are treated. "Calls to the
  functions listed above, whenever they occur while invocation k of the target
  is on the stack" and "direct calls only" are different answers — pick one
  and say it.

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape (never `callee_sequence`
or bare name lists; call order uses `{file, func}` objects).

Hardness levers:
- Prefer targets whose callees are chosen dynamically (dispatch dicts,
  getattr, polymorphism) so the sequence isn't readable statically.
- Choose inputs where the callee sequence differs between invocations and ask
  about a specific one.
- Configure TRACE_FUNC with every function name involved, and verify the
  trace captures all of them before parsing.
