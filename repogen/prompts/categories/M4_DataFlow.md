# M4_DataFlow — path-sensitive data flow (harder)

Like S4, but the def-use structure must depend on control flow across
branches, loops, or multiple invocations, combined in one answer.

Good question archetypes (pick ONE):
- Def-use pairs per invocation for variables redefined inside branches: a map
  from invocation index to the pairs observed in it (pairs may differ between
  invocations).
- Loop-carried flow: pairs where the def happens in iteration i and the use
  in iteration i+1 (define how iterations are identified).
- Kill analysis, dynamic edition: defs that were never used (dead stores at
  runtime) alongside the used pairs — two lists.

Answer definition rules:
- Enumerate tracked variables exactly; define def/use as in S4 (parameters
  defined at the `def` line).
- State full sort order and, for per-invocation maps, invocation counting.

Template shape example:
```json
{"observed_def_use_pairs": [{"variable": "str", "def_line": "int", "use_line": "int"}],
 "dead_defs": [{"variable": "str", "def_line": "int"}]}
```

Hardness levers:
- Inputs must make different defs reach the same use across invocations.
- Include at least one variable whose def in a loop body is killed on some
  iterations only.
- Aim for >=10 pairs plus a non-empty second list.
