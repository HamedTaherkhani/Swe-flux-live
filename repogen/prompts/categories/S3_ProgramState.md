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
- Values are reported as Python `repr` strings; say so in the question.

Template shape example:
```json
{"observed_state": [{"variable": "str", "value": "str"}]}
```
or
```json
{"value_history": [{"step": "int", "value": "str"}]}
```

Hardness levers:
- Pick variables that are reassigned or mutated several times before the
  observation point.
- Pick an observation point inside a branch or loop body, so reaching it at
  the k-th time requires tracking control flow.
- Ask about >=3 variables or >=5 history steps.
