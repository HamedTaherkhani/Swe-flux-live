import random
import unittest

from lark import Token, Tree


class TestTopdownTraversalLoopDynamics(unittest.TestCase):
    def _exercise_profile(self, tag, depth, span, profile):
        seed = sum(
            (index + 3) * (ord(character) + index * index)
            for index, character in enumerate(tag)
        )
        rng = random.Random(seed ^ (depth << (profile % 5)) ^ (span * (profile + 1)))
        serial = 0
        node_pool = []

        def make_node(level, path_weight):
            nonlocal serial
            serial += 1
            node_number = serial
            width = (
                3
                + rng.randrange(span)
                + rng.randrange(1 + span // 2)
                + (path_weight + node_number + profile) % 3
            )
            children = []

            for index in range(width):
                mix = (
                    rng.randrange(1, span * 5 + 7)
                    + path_weight
                    + node_number * (index + 1)
                    + profile * profile
                )
                required_branch = (
                    level > 0
                    and index == (path_weight + node_number + profile) % width
                )
                extra_branch = (
                    level > 0
                    and (mix + index + level) % (4 + profile % 5) == 0
                )
                if required_branch or extra_branch:
                    children.append(
                        make_node(level - 1, path_weight + mix + index * index)
                    )
                elif (profile + level + index) % 11 == 0 and level:
                    children.append(Tree("hollow_%s_%s" % (tag, mix), []))
                else:
                    leaf_kind = (mix + profile + index) % 4
                    if leaf_kind == 0:
                        leaf = Token(
                            "TOK_%s" % (mix % (span + 3)),
                            "%s:%s:%s" % (tag, node_number, mix),
                        )
                    elif leaf_kind == 1:
                        leaf = (tag, mix % (span * span + 1))
                    elif leaf_kind == 2:
                        leaf = mix * (profile + 2) - path_weight
                    else:
                        leaf = None
                    children.append(leaf)

            node = Tree(
                "node_%s_%s_%s_%s" % (tag, level, node_number, path_weight % 17),
                children,
            )
            node_pool.append(node)
            return node

        root = make_node(depth, seed % (span * 3 + 1))
        if profile % 4 == 3:
            reusable = [
                node
                for node in node_pool
                if node is not root and (len(node.children) + profile) % 3
            ]
            for offset, node in enumerate(reusable[:: 1 + profile % 3]):
                if (offset + len(tag)) % 2 == 0:
                    root.children.append(node)

        visited = list(root.iter_subtrees_topdown())

        self.assertIs(visited[0], root)
        self.assertTrue(all(isinstance(node, Tree) for node in visited))
        self.assertGreater(len(visited), depth)
        self.assertTrue(any(not isinstance(child, Tree) for child in root.children))
        self.assertTrue(root.data.startswith("node_" + tag))
        self.assertGreater(
            sum((index + 1) * len(str(node.data)) for index, node in enumerate(visited)),
            len(visited),
        )

    def test_amber_switchbacks(self):
        self._exercise_profile("amber_switchbacks", 2, 5, 0)

    def test_boreal_crossing(self):
        self._exercise_profile("boreal_crossing", 3, 4, 1)

    def test_cinder_archipelago(self):
        self._exercise_profile("cinder_archipelago", 4, 3, 2)

    def test_delta_shared_paths(self):
        self._exercise_profile("delta_shared_paths", 3, 6, 3)

    def test_ember_wide_basin(self):
        self._exercise_profile("ember_wide_basin", 2, 8, 4)

    def test_fir_hollow_nodes(self):
        self._exercise_profile("fir_hollow_nodes", 4, 4, 5)

    def test_glacier_long_forks(self):
        self._exercise_profile("glacier_long_forks", 5, 3, 6)

    def test_harbor_reused_branches(self):
        self._exercise_profile("harbor_reused_branches", 3, 7, 7)

    def test_indigo_leaf_fanout(self):
        self._exercise_profile("indigo_leaf_fanout", 2, 9, 8)

    def test_juniper_deep_current(self):
        self._exercise_profile("juniper_deep_current", 5, 4, 9)

    def test_karst_irregular_steps(self):
        self._exercise_profile("karst_irregular_steps", 4, 6, 10)

    def test_lantern_dag_canopy(self):
        self._exercise_profile("lantern_dag_canopy", 3, 8, 11)


if __name__ == "__main__":
    unittest.main()
