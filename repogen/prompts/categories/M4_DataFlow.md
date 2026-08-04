# M4_DataFlow — path-sensitive data flow (harder)

Like S4, but the def-use structure must depend on control flow across
branches, loops, or multiple invocations, combined in one answer.

Good question archetypes (pick ONE):
- All unique observed def-use pairs (union across invocations) for variables
  redefined inside branches/loops, chosen so the pair set depends on the
  actual paths taken — the answer shape is identical to S4.
- The same with loop-carried flow included: defs from one iteration used in a
  later one — still emitted as `{variable, def_line, use_line}` pairs.

Answer definition rules:
- Enumerate tracked variables exactly; define def/use as in S4 (parameters
  defined at the `def` line), including the augmented-assignment,
  loop-header, and comprehension rules.
- State full sort order (variable, then def_line, then use_line, ascending)
  and dedup.

Template: use THE canonical template for this category (see the canonical
answer templates section) — same shape as S4; hardness comes from the
scenario, not the schema.

Hardness levers:
- Inputs must make different defs reach the same use across invocations.
- Include at least one variable whose def in a loop body is killed on some
  iterations only.
- Aim for >=10 pairs plus a non-empty second list.
