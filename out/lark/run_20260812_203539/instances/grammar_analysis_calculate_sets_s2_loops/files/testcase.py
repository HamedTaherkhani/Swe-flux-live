import random
import unittest

from lark.grammar import NonTerminal, Rule, Terminal
from lark.parsers.grammar_analysis import calculate_sets


class TestCalculateSetsLoopDynamics(unittest.TestCase):
    def test_seeded_dependency_propagation(self):
        tag = "layered-nullable-propagation"
        rng = random.Random(tag)
        node_count = sum((ord(char) % len("lattice")) + 1 for char in tag)

        nodes = [NonTerminal("node_%s" % index) for index in range(node_count)]
        terminals = [
            Terminal("token_%s" % index)
            for index in range(1 + node_count // len(tag))
        ]

        rules = [
            Rule(nodes[index], [nodes[index + 1]])
            for index in range(node_count - 1)
        ]
        rules.append(Rule(nodes[-1], [terminals[-1]]))

        for index, node in enumerate(nodes):
            if (index * index + ord(tag[index % len(tag)])) % len("nullable") == 0:
                rules.append(Rule(node, []))
            if index + 2 < node_count and rng.randrange(len("branching")) < len("fork"):
                terminal = terminals[(index + rng.randrange(len(terminals))) % len(terminals)]
                rules.append(Rule(node, [nodes[index + 2], terminal]))

        rng.shuffle(rules)
        first, follow, nullable = calculate_sets(rules)

        all_symbols = set(nodes) | set(terminals)
        self.assertEqual(set(first), all_symbols)
        self.assertEqual(set(follow), all_symbols)
        self.assertTrue(nullable)
        self.assertTrue(first[nodes[0]])
        self.assertTrue(all(first[terminal] == {terminal} for terminal in terminals))


if __name__ == "__main__":
    unittest.main()
