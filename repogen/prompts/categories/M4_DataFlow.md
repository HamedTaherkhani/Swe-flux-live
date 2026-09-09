# M4_DataFlow — path-sensitive data flow (harder)

Like S4, but the def-use structure must depend on control flow across
branches, loops, and many invocations, combined in one answer — and each pair
must be reported WITH how often it was observed.

## Never answer with a bare pair union

A deduplicated set of `{variable, def_line, use_line}` pairs degenerates here.
Across the 10-15 test methods M4 requires, the union saturates toward every
statically possible pair, so a solver can read the answer off the source
without simulating the paths. Attach a `count` to every pair.

## Required question archetype

All observed def-use pairs with per-pair observation counts — canonical
template `observed_def_use_pairs`, a list of
`{variable, def_line, use_line, count}` objects.

- `count` = how many times that exact (variable, def_line, use_line) flow was
  observed, summed across ALL invocations in ALL test methods.
- Pairs that never occur are simply absent (unlike M1/M6, the pair space is
  not enumerable in advance) — so hardness comes from the counts and from
  which pairs appear at all.

## Answer definition rules

- Enumerate tracked variables exactly; define def/use as in S4 (parameters
  defined at the `def` line), including the augmented-assignment, loop-header,
  and comprehension rules.
- Define an observation precisely: one use event reached by that def, so a use
  inside a loop body counts once per iteration.
- State that counts are totals across all test methods in the class.
- State full sort order (variable, then def_line, then use_line, ascending)
  and that the triple is unique — the count carries multiplicity, so there is
  no duplicate row.

## Hardness levers

- Inputs must make DIFFERENT defs reach the same use across invocations, so
  the pair set alone is ambiguous and only the counts separate the scenarios.
- Include at least one variable whose def in a loop body is killed on some
  iterations only — its count must not equal the iteration count.
- Drive loop-carried flow (a def from one iteration used in a later one) so
  some counts are far larger than the number of test methods.
- Aim for >= 10 distinct pairs with non-uniform counts spanning a range
  (e.g. 1, 3, 12, 40) — never all-ones, which degenerates back into a set.
