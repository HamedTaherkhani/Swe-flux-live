import random
import unittest

from lark import Token, Tree


class TestTreeFindTokenLoopDynamics(unittest.TestCase):
    def _exercise_generated_tree(self, tag, depth, span):
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate(tag)))
        serial = 0
        wanted_type = "WANTED_" + tag.upper()

        def make_node(level, path_weight):
            nonlocal serial
            serial += 1
            node_number = serial
            width = (
                3
                + rng.randrange(span * 2)
                + rng.randrange(span * 2)
                + (node_number + level + path_weight) % 3
            )
            children = []
            has_wanted = False

            for index in range(width):
                mix = rng.randrange(1, 9) + node_number + index + path_weight
                must_descend = level > 0 and index == (node_number + path_weight) % width
                may_descend = level > 0 and index == width - 1 and mix % 7 == 0
                if must_descend or may_descend:
                    subtree, subtree_has_wanted = make_node(
                        level - 1, path_weight + index + mix
                    )
                    children.append(subtree)
                    has_wanted = has_wanted or subtree_has_wanted
                    continue

                token_type = wanted_type if mix % 5 == 1 else "OTHER_" + str(mix % 6)
                has_wanted = has_wanted or token_type == wanted_type
                value = "%s_%s_%s_%s" % (tag, node_number, index, mix)
                children.append(Token(token_type, value))

            if not has_wanted:
                value = "%s_%s_fallback_%s" % (tag, node_number, path_weight)
                children.append(Token(wanted_type, value))
                has_wanted = True

            tree = Tree("node_%s_%s_%s" % (tag, node_number, level), children)
            return tree, has_wanted

        tree, _ = make_node(depth, len(tag) % 7)
        matches = list(tree.find_token(wanted_type))

        self.assertTrue(matches)
        self.assertTrue(all(token.type == wanted_type for token in matches))
        self.assertEqual(len(matches), len({token.value for token in matches}))
        self.assertTrue(tree.data.startswith("node_" + tag))

    def test_amber_canopy(self):
        self._exercise_generated_tree("am", 7, 28)

    def test_birch_delta(self):
        self._exercise_generated_tree("birchdeltaX", 6, 30)

    def test_cobalt_harbor(self):
        self._exercise_generated_tree("cobalt", 8, 26)

    def test_driftwood_lane(self):
        self._exercise_generated_tree("driftwoodlaneextra", 7, 32)

    def test_ember_forest(self):
        self._exercise_generated_tree("ember", 6, 24)

    def test_falcon_ridge(self):
        self._exercise_generated_tree("falconridgepeak", 8, 29)

    def test_glacier_meadow(self):
        self._exercise_generated_tree("glacier", 7, 31)

    def test_hazel_quarry(self):
        self._exercise_generated_tree("hazelquarrymine", 6, 33)

    def test_indigo_stream(self):
        self._exercise_generated_tree("indigo", 8, 27)

    def test_juniper_valley(self):
        self._exercise_generated_tree("junipervalleydeep", 7, 28)

    def test_kingfisher_bay(self):
        self._exercise_generated_tree("kingfisher", 8, 30)

    def test_lantern_grove(self):
        self._exercise_generated_tree("lanterngrovehill", 6, 29)


if __name__ == "__main__":
    unittest.main()