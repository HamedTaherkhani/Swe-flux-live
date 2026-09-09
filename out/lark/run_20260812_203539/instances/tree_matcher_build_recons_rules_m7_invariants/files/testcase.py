import random
import unittest
from collections import defaultdict

from lark.grammar import NonTerminal, Rule, RuleOptions, Terminal
from lark.tree_matcher import TreeMatcher


class ProbeRule:
    """Rule-shaped input with a compact, trace-friendly representation."""

    def __init__(self, origin, expansion, alias, expand1):
        self.origin = origin
        self.expansion = tuple(expansion)
        self.alias = alias
        self.options = RuleOptions(expand1=expand1)

    def __repr__(self):
        retained = sum(
            not (symbol.is_term and symbol.filter_out)
            for symbol in self.expansion
        )
        return (
            "ProbeRule("
            f"origin={self.origin.name!r},alias={self.alias!r},"
            f"expand1={self.options.expand1!r},"
            f"expansion_len={len(self.expansion)!r},retained_len={retained!r})"
        )


def build_rules(seed, count, flavor):
    rng = random.Random(seed * 1009 + flavor * 97)
    indices = list(range(count))
    rng.shuffle(indices)
    rules = []

    for position, index in enumerate(indices):
        hidden = (index * 5 + seed + flavor) % 9 in (0, 1)
        stem = f"n{seed}_{index}_{flavor}"
        origin = NonTerminal(("_" if hidden else "") + stem)

        expand1 = (index * 11 + seed + flavor) % 8 in (0, 3)
        alias = None
        if (index * 7 + seed + 2 * flavor) % 6 == 0:
            alias = f"a{(index + flavor) % 13}_{seed}"

        if position == (seed + flavor) % count:
            expansion = [origin]
            alias = None
            expand1 = False
        elif expand1:
            kept = NonTerminal(f"leaf_{rng.randrange(count + 17)}")
            expansion = [kept]
            if (index + flavor) % 3 == 0:
                expansion.append(Terminal(f"DROP_{seed}_{index}", filter_out=True))
        else:
            width = 1 + rng.randrange(4)
            expansion = []
            for slot in range(width):
                marker = rng.randrange(7)
                if marker < 2:
                    expansion.append(
                        Terminal(
                            f"T_{seed}_{index}_{slot}",
                            filter_out=((index + slot + flavor) % 4 == 0),
                        )
                    )
                else:
                    expansion.append(
                        NonTerminal(f"ref_{(index * 3 + slot + marker) % (count // 2 + 9)}")
                    )

        rules.append(ProbeRule(origin, expansion, alias, expand1))

    wide = NonTerminal(f"wide_{seed}_{flavor}")
    wide_options = (NonTerminal(f"left_{seed}"), NonTerminal(f"right_{flavor}"))
    rules.append(ProbeRule(wide, wide_options, None, True))
    if flavor == 7:
        extra = wide_options + (Terminal(f"EXTRA_{seed}"),)
        rules.append(ProbeRule(wide, extra, None, True))

    return rules


class TestBuildReconsRulesInvariants(unittest.TestCase):
    def exercise(self, seed, count, flavor):
        matcher = object.__new__(TreeMatcher)
        matcher.rules_for_root = defaultdict(list)
        source_rules = build_rules(seed, count, flavor)

        produced = list(matcher._build_recons_rules(source_rules))

        self.assertTrue(produced)
        self.assertTrue(all(isinstance(rule, Rule) for rule in produced))
        self.assertTrue(
            all(isinstance(group, list) for group in matcher.rules_for_root.values())
        )

    def test_alias_dense_odd(self):
        self.exercise(17, 23, 4)

    def test_discard_heavy_even(self):
        self.exercise(29, 28, 9)

    def test_expand_mix_prime(self):
        self.exercise(41, 31, 2)

    def test_hidden_symbols_short(self):
        self.exercise(53, 19, 11)

    def test_long_rotated_rules(self):
        self.exercise(67, 37, 5)

    def test_narrow_expansions(self):
        self.exercise(71, 22, 13)

    def test_repeated_expand_origin(self):
        self.exercise(83, 26, 7)

    def test_self_recursive_offset(self):
        self.exercise(97, 34, 1)

    def test_sparse_aliases(self):
        self.exercise(101, 21, 16)

    def test_terminal_biased(self):
        self.exercise(113, 29, 8)

    def test_wide_expansions(self):
        self.exercise(127, 33, 10)

    def test_wrapped_index_cycle(self):
        self.exercise(139, 24, 14)
