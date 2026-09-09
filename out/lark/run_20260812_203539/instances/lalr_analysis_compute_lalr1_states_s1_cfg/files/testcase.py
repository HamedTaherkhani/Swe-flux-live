import random
import unittest

from lark import Lark
from lark.common import ParserConf
from lark.parsers.lalr_analysis import LALR_Analyzer


_GRAMMAR_LOADER_WARMUP = Lark('start: "warm"', parser="earley")


def build_grammar(seed, depth):
    rng = random.Random(seed)
    operator_words = []
    for index in range(depth):
        width = 3 + rng.randrange(5)
        suffix = "".join(chr(97 + rng.randrange(26)) for _ in range(width))
        operator_words.append(f"op{index}_{suffix}")

    lines = ["start: level_0"]
    for index, operator_word in enumerate(operator_words):
        successor = f"level_{index + 1}" if index + 1 < depth else "atom"
        lines.append(
            f"?level_{index}: level_{index} OP_{index} {successor} | {successor}"
        )
        lines.append(f'OP_{index}: "{operator_word}"')
    lines.extend(
        [
            '?atom: NAME | "(" level_0 ")"',
            "NAME: /[a-z][a-z0-9_]*/",
            '%ignore " "',
        ]
    )
    return "\n".join(lines)


def prepare_analyzer(seed, depth, debug):
    grammar = build_grammar(seed, depth)
    grammar_model = Lark(grammar, parser="earley", start="start")
    parser_conf = ParserConf(grammar_model.rules, {}, grammar_model.options.start)
    analyzer = LALR_Analyzer(parser_conf, debug=debug)
    analyzer.compute_lr0_states()
    analyzer.compute_reads_relations()
    analyzer.compute_includes_lookback()
    analyzer.compute_lookaheads()

    itemsets = list(analyzer.lr0_itemsets)
    for itemset in itemsets:
        itemset.closure = tuple(sorted(itemset.closure, key=repr))
        itemset.transitions = dict(
            sorted(itemset.transitions.items(), key=lambda pair: pair[0].name)
        )
        itemset.lookaheads = {
            lookahead: tuple(sorted(rules, key=str))
            for lookahead, rules in sorted(
                itemset.lookaheads.items(), key=lambda pair: pair[0].name
            )
        }
    analyzer.lr0_itemsets = tuple(
        sorted(itemsets, key=lambda itemset: tuple(map(repr, itemset.closure)))
    )
    return analyzer


class TestGeneratedLalrControlFlow(unittest.TestCase):
    def test_three_direct_table_constructions(self):
        rng = random.Random(8675309)
        analyzers = [
            prepare_analyzer(
                rng.randrange(100000, 1000000),
                12 + rng.randrange(5),
                debug=(position == 1),
            )
            for position in range(3)
        ]

        for analyzer in analyzers:
            analyzer.compute_lalr1_states()

        for analyzer in analyzers:
            self.assertTrue(analyzer.parse_table.states)
            self.assertEqual(
                set(analyzer.parse_table.start_states),
                set(analyzer.lr0_start_states),
            )
