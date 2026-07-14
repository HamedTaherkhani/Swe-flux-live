# M3_ProgramState — multi-variable / multi-point state (harder)

Like S3, but the answer must combine state observations across MULTIPLE
variables AND multiple program points or invocations.

Good question archetypes (pick ONE):
- Snapshot table: values (reprs) of >=4 named variables at TWO distinct
  program points (e.g. after line L1 first executes and at return) for a
  stated invocation.
- Cross-invocation history: for each invocation, the final value of a set of
  named variables at return.
- Mutation timeline: ordered `(line, variable, new_value)` triples for a set
  of variables during one invocation.

Answer definition rules:
- Values are Python `repr` strings; observation points defined by line number
  and execution count ("the k-th time line L executes").
- Sort deterministic: by point, then variable name, or chronological for
  timelines — state which.

Template shape example:
```json
{"mutation_timeline": [{"line": "int", "variable": "str", "value": "str"}]}
```

Hardness levers:
- Choose variables mutated in interleaved branches/loops, so the timeline
  requires precise path tracking.
- Include at least one variable holding a container that is mutated in place.
- Answer should contain >=8 entries.
