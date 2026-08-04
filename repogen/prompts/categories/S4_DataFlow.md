# S4_DataFlow — def-use pairs observed at runtime

Ask about the dynamic def-use relationships of named local variables in the
target function during the test run.

Good question archetypes (pick ONE):
- All unique observed def-use pairs for an explicit list of variable names:
  objects `{variable, def_line, use_line}` where the value assigned at
  def_line is read at use_line before being redefined.
- The same but restricted to one or two heavily-redefined variables, chosen
  so which def reaches which use depends on the actual path taken.

Answer definition rules:
- Enumerate the tracked variable names exactly in the question.
- Define "def" (assignment/parameter binding; parameters count as defined at
  the `def` line) and "use" (the variable is read on that line).
- State explicitly how augmented assignment (`x += 1`) is treated (it reads
  then writes: a use of the old def AND a new def on that line), and how
  loop headers (`for x in ...` redefines x each iteration) and
  comprehension-local variables are treated. The parser must match exactly.
- State sort order: by variable, then def_line, then use_line, ascending.

Template: use THE canonical template for this category (see the canonical
answer templates section) — 114 of 118 verified S4 instances share it; do not
deviate.

Hardness levers:
- Track variables redefined on multiple lines (including inside branches), so
  which def reaches which use depends on the actual path.
- Choose inputs that exercise both sides of at least one branch across
  invocations, producing pairs a static reader would miss or over-report.
- Aim for >=8 pairs in the answer.
