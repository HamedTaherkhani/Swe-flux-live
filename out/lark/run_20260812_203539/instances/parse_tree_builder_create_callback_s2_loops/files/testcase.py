import random
import unittest

from lark.grammar import NonTerminal, Rule, RuleOptions, Terminal
from lark.parse_tree_builder import ParseTreeBuilder
from lark.tree import Tree
from lark.visitors import Transformer_InPlace, v_args


class TestCreateCallbackLoopDynamics(unittest.TestCase):
    def test_seeded_rule_builder_matrix(self):
        seed_phrase = "callback-wrapper-constellation"
        rng = random.Random(seed_phrase)
        rule_count = len(seed_phrase) + sum(
            (ord(char) + index) % len("orbit")
            for index, char in enumerate(seed_phrase)
        )

        rules = []
        for index in range(rule_count):
            width = len("arc") + rng.randrange(len("paths"))
            expansion = []
            for position in range(width):
                symbol_name = "symbol_%s_%s" % (index, position)
                if (rng.randrange(len("terminal")) + index + position) % len("axis") == 0:
                    expansion.append(
                        Terminal(symbol_name.upper(), filter_out=bool(rng.getrandbits(1)))
                    )
                else:
                    prefix = "_" if rng.randrange(len("branch")) < len("triad") else ""
                    expansion.append(NonTerminal(prefix + symbol_name))

            empty_indices = ()
            if (index + rng.randrange(len("placeholder"))) % len("phase") < len("arc"):
                slots = []
                for _ in expansion:
                    slots.extend([True] * rng.randrange(len("arc")))
                    slots.append(False)
                slots.extend([True] * rng.randrange(len("arc")))
                empty_indices = tuple(slots)

            alias = "alias_%s" % index if rng.randrange(len("aliasing")) < len("arc") else None
            template_source = (
                "template_%s" % index
                if alias is None and rng.randrange(len("template")) < len("arc")
                else None
            )
            options = RuleOptions(
                keep_all_tokens=bool(rng.getrandbits(1)),
                expand1=rng.randrange(len("expand")) < len("arc"),
                template_source=template_source,
                empty_indices=empty_indices,
            )
            rules.append(
                Rule(
                    NonTerminal("rule_%s" % index),
                    expansion,
                    order=index,
                    alias=alias,
                    options=options,
                )
            )

        method_table = {}
        for index, rule in enumerate(rules):
            callback_name = rule.alias or rule.options.template_source or rule.origin.name
            selector = (index * len(callback_name) + rng.randrange(len("dispatch"))) % len(
                "routes"
            )
            if selector < len("path"):
                def callback(self, children, marker=index):
                    return marker, children

                if selector % len("pair") == 0:
                    callback = v_args(inline=True)(callback)
                method_table[callback_name] = callback

        GeneratedTransformer = type(
            "GeneratedTransformer",
            (Transformer_InPlace,),
            method_table,
        )
        builder = ParseTreeBuilder(
            rules,
            Tree,
            propagate_positions=True,
            ambiguous=True,
            maybe_placeholders=True,
        )

        callbacks = builder.create_callback(GeneratedTransformer())

        self.assertEqual(set(callbacks), set(rules))
        self.assertTrue(all(callable(callback) for callback in callbacks.values()))
        self.assertGreater(len(builder.rule_builders), len(seed_phrase))


if __name__ == "__main__":
    unittest.main()
