import random
import unittest

from lark import Tree
from lark.tree_templates import Template


class TestTemplateSearchDynamics(unittest.TestCase):
    def _case(self, seed, mode):
        rng = random.Random(seed)

        def payload(index):
            label = chr(ord("a") + ((index + seed) % len("abcdefghi")))
            return Tree("node_" + label, [Tree("leaf", [label * (1 + index % 3)])])

        anchor_payload = payload(mode)
        if mode == 0:
            pattern = Tree("pair", ["fixed", Tree("var", ["$item"])])
            anchor = Tree("pair", ["fixed", anchor_payload])
        elif mode == 1:
            pattern = Tree(
                "reverse_pair", [Tree("var", ["$item"]), "fixed"]
            )
            anchor = Tree("reverse_pair", [anchor_payload, "fixed"])
        elif mode == 2:
            pattern = Tree(
                "pair",
                ["fixed", Tree("pair", ["fixed", Tree("var", ["$item"])])],
            )
            anchor = Tree("pair", ["fixed", Tree("pair", ["fixed", anchor_payload])])
        elif mode == 3:
            pattern = Tree("pair", ["fixed", Tree("leaf", ["sentinel"])])
            anchor = Tree("pair", ["fixed", Tree("leaf", ["sentinel"])])
        elif mode == 4:
            pattern = Tree(
                "pair", ["fixed", Tree("var", ["$item"]), "trailer"]
            )
            anchor = Tree("pair", ["fixed", anchor_payload, "trailer"])
        else:
            pattern = Tree("var", ["$item"])
            anchor = Tree("special", [anchor_payload])

        branches = [anchor]
        for index in range(len("workload") + seed % 4):
            value = payload(index + mode)
            choice = (rng.randrange(len("choices")) + index + mode) % 6
            if choice == 0:
                node = Tree("pair", ["fixed", value])
            elif choice == 1:
                node = Tree("pair", ["other", value])
            elif choice == 2:
                node = Tree("pair", [value, "fixed"])
            elif choice == 3:
                node = Tree("pair", ["fixed", value, Tree("extra", [])])
            elif choice == 4:
                node = Tree("different", ["fixed", value])
            else:
                node = Tree("pair", ["fixed", Tree("pair", ["fixed", value])])
            branches.append(Tree("group_" + str(index % 3), [node, payload(index)]))

        root = Tree("root_" + str(mode), branches)
        matches = list(Template(pattern).search(root))

        self.assertIsInstance(matches, list)
        if mode == 3:
            self.assertFalse(matches)
        else:
            self.assertTrue(matches)
            self.assertTrue(all(isinstance(found, Tree) for found, _ in matches))
            self.assertTrue(all(mapping for _, mapping in matches))

    def test_fixed_then_variable_seed_zero(self):
        self._case(0, 0)

    def test_variable_then_fixed_seed_one(self):
        self._case(1, 1)

    def test_nested_pattern_seed_two(self):
        self._case(2, 2)

    def test_exact_pattern_seed_three(self):
        self._case(3, 3)

    def test_three_child_pattern_seed_four(self):
        self._case(4, 4)

    def test_whole_subtree_variable_seed_five(self):
        self._case(5, 5)

    def test_fixed_then_variable_seed_six(self):
        self._case(6, 0)

    def test_variable_then_fixed_seed_seven(self):
        self._case(7, 1)

    def test_nested_pattern_seed_eight(self):
        self._case(8, 2)

    def test_exact_pattern_derived_seed(self):
        self._case(len("nine-seed"), 3)

    def test_three_child_pattern_derived_seed(self):
        self._case(len("ten-seed!!"), 4)

    def test_whole_subtree_variable_derived_seed(self):
        self._case(len("eleven-seed"), 5)
