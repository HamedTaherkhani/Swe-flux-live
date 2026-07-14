# S4_DataFlow — def-use pairs observed at runtime

Ask about the dynamic def-use relationships of named local variables in the
target function during the test run.

Good question archetypes (pick ONE):
- All unique observed def-use pairs for an explicit list of variable names:
  objects `{variable, def_line, use_line}` where the value assigned at
  def_line is read at use_line before being redefined.
- For one variable, the ordered chain of (def_line, use_lines...) events.
- Which static def-use pairs (visible in the source) were NOT exercised by
  the run.

Answer definition rules:
- Enumerate the tracked variable names exactly in the question.
- Define "def" (assignment/parameter binding; parameters count as defined at
  the `def` line) and "use" (the variable is read on that line).
- State sort order: by variable, then def_line, then use_line, ascending.

Template shape example:
```json
{"observed_def_use_pairs": [{"variable": "str", "def_line": "int", "use_line": "int"}]}
```

Hardness levers:
- Track variables redefined on multiple lines (including inside branches), so
  which def reaches which use depends on the actual path.
- Choose inputs that exercise both sides of at least one branch across
  invocations, producing pairs a static reader would miss or over-report.
- Aim for >=8 pairs in the answer.
