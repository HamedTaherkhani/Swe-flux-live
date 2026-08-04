# S3_ProgramState — local state at a program point

Ask about the concrete values of local variables at a precise moment during
execution of the target function.

Good question archetypes (pick ONE):
- The values of named local variables immediately after line L executes for
  the k-th time.
- The full history of values a single named variable takes during one
  invocation (ordered).
- The value of each named variable at function return (of a stated invocation).

Answer definition rules:
- State the exact observation point: "immediately after line L has executed
  for the k-th time during the test run".
- Values are reported as Python `repr` strings; say so in the question, and
  note that containers are the `repr` of the whole container (so strings keep
  their quotes, `None`/`True` are Python spellings, and embedded newlines
  appear as real newline characters inside the JSON string). Avoid values
  whose repr is unstable (memory addresses, unordered sets/dicts of
  non-sorted keys) — pick different variables instead.

Template: use a canonical template for this category (see the canonical
answer templates section) — do not invent another shape.

Hardness levers:
- Track variables holding COMPUTED state (accumulators, merged/transformed
  structures, derived indices) — never variables that merely hold a copy of a
  test input, or the answer is readable off the test file (`answer_leak`).
- Pick variables that are reassigned or mutated several times before the
  observation point.
- Pick an observation point inside a branch or loop body, so reaching it at
  the k-th time requires tracking control flow.
- Ask about >=3 variables or >=5 history steps.
