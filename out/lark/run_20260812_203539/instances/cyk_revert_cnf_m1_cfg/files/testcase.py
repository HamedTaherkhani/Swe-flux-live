import random
import unittest

from lark.grammar import NonTerminal, Terminal
from lark.parsers.cyk import Rule, RuleNode, UnitSkipRule, revert_cnf


def _rule(name, rhs=(), weight=0, alias=None):
    return Rule(
        NonTerminal(name),
        list(rhs),
        weight=weight,
        alias=alias if alias is not None else name,
    )


def _terminal(label, index):
    return Terminal(f"{label}_{index}")


def _term_wrapper(label, index):
    token = _terminal(label, index)
    rule = _rule(f"__T_{label}_{index}", [token])
    return RuleNode(rule, [token], weight=index % 5)


def _ordinary_leaf(label, index):
    token = _terminal(label, index)
    return RuleNode(
        _rule(f"leaf_{label}_{index}", [token], weight=index % 7),
        [token],
        weight=index % 7,
    )


def _unit_node(label, index, rng):
    skipped = []
    previous = NonTerminal(f"payload_{label}_{index}")
    for depth in range(1 + rng.randrange(5)):
        current = NonTerminal(f"unit_{label}_{index}_{depth}")
        skipped.append(
            Rule(
                current,
                [previous],
                weight=depth + 1,
                alias=f"alias_{label}_{index}_{depth}",
            )
        )
        previous = current

    rhs = [NonTerminal(f"resolved_{label}_{index}")]
    unit_rule = UnitSkipRule(
        NonTerminal(f"outer_{label}_{index}"),
        rhs,
        skipped,
        weight=sum(rule.weight for rule in skipped) + 3,
        alias=f"outer_alias_{label}_{index}",
    )
    child_count = 1 + rng.randrange(4)
    children = [
        _term_wrapper(label, index * 17 + offset)
        if (index + offset) % 3 == 0
        else _ordinary_leaf(label, index * 17 + offset)
        for offset in range(child_count)
    ]
    return RuleNode(unit_rule, children, weight=unit_rule.weight)


def _composite_node(label, index, rng):
    branch_count = 2 + rng.randrange(5)
    branches = []
    for offset in range(branch_count):
        serial = index * 23 + offset
        if (index + offset) % 4 == 0:
            branches.append(_term_wrapper(label, serial))
        elif (index + offset) % 4 == 1:
            branches.append(_terminal(label, serial))
        elif (index + offset) % 4 == 2:
            spread_children = [
                _ordinary_leaf(label, serial * 7 + inner)
                for inner in range(2 + rng.randrange(4))
            ]
            branches.append(
                RuleNode(
                    _rule(f"__SP_{label}_{serial}"),
                    spread_children,
                    weight=serial % 9,
                )
            )
        else:
            branches.append(_unit_node(label, serial, rng))
    return RuleNode(_rule(f"branch_{label}_{index}"), branches)


def _build_case(label, flavor):
    seed = sum((position + 1) * ord(character) for position, character in enumerate(label))
    rng = random.Random(seed ^ ((flavor + 3) * 7919))
    width = len(label) + 11 + rng.randrange(13)
    children = []
    for index in range(width):
        selector = (rng.randrange(29) + index * (flavor + 1)) % 6
        if selector == 0:
            child = _terminal(label, index)
        elif selector == 1:
            child = _term_wrapper(label, index)
        elif selector == 2:
            child = _ordinary_leaf(label, index)
        elif selector == 3:
            spread = [
                _ordinary_leaf(label, index * 31 + offset)
                for offset in range(2 + rng.randrange(5))
            ]
            child = RuleNode(_rule(f"__SP_{label}_{index}"), spread)
        elif selector == 4:
            child = _unit_node(label, index, rng)
        else:
            child = _composite_node(label, index, rng)
        children.append(child)

    if flavor % 3:
        root_rule = _rule(f"root_{label}", weight=flavor % 7)
    else:
        skipped = [
            _rule(
                f"root_unit_{label}_{depth}",
                [NonTerminal(f"root_rhs_{label}_{depth}")],
                weight=depth + 1,
            )
            for depth in range(1 + rng.randrange(5))
        ]
        root_rule = UnitSkipRule(
            NonTerminal(f"root_{label}"),
            [NonTerminal(f"root_result_{label}")],
            skipped,
            weight=sum(rule.weight for rule in skipped) + flavor,
            alias=f"root_alias_{label}",
        )
    return RuleNode(root_rule, children), width


def _exercise(testcase, label, flavor):
    source, width = _build_case(label, flavor)
    result = revert_cnf(source)

    testcase.assertIsInstance(result, RuleNode)
    stack = [result]
    visited = 0
    terminal_count = 0
    while stack:
        item = stack.pop()
        visited += 1
        if isinstance(item, Terminal):
            terminal_count += 1
            continue
        testcase.assertIsInstance(item, RuleNode)
        testcase.assertFalse(item.rule.lhs.name.startswith("__T_"))
        testcase.assertFalse(item.rule.lhs.name.startswith("__SP_"))
        stack.extend(item.children)
    testcase.assertGreater(visited, width)
    testcase.assertGreater(terminal_count, 0)


class TestRevertCnfAggregateControlFlow(unittest.TestCase):
    def test_amber_canopy(self):
        _exercise(self, "amber_canopy", 0)

    def test_brisk_delta(self):
        _exercise(self, "brisk_delta", 1)

    def test_cobalt_finch(self):
        _exercise(self, "cobalt_finch", 2)

    def test_dappled_grove(self):
        _exercise(self, "dappled_grove", 3)

    def test_ember_harbor(self):
        _exercise(self, "ember_harbor", 4)

    def test_frosted_isle(self):
        _exercise(self, "frosted_isle", 5)

    def test_golden_junction(self):
        _exercise(self, "golden_junction", 6)

    def test_hushed_keystone(self):
        _exercise(self, "hushed_keystone", 7)

    def test_indigo_lantern(self):
        _exercise(self, "indigo_lantern", 8)

    def test_jade_meadow(self):
        _exercise(self, "jade_meadow", 9)

    def test_kindled_north(self):
        _exercise(self, "kindled_north", 10)

    def test_lucid_orchard(self):
        _exercise(self, "lucid_orchard", 11)
