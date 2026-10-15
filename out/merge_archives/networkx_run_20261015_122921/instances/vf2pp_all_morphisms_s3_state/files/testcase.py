import unittest

import networkx as nx


def _build_pair():
    first = nx.random_regular_graph(3, 14, seed=0)
    second = nx.random_regular_graph(3, 14, seed=100)
    second = nx.relabel_nodes(second, {n: 5 * n + 11 for n in second})
    return first, second


class TestVF2ppExhaustiveSearch(unittest.TestCase):
    def test_cubic_pair_not_isomorphic(self):
        first, second = _build_pair()
        # Same degree sequence, so the search cannot be pruned up front.
        self.assertEqual(
            sorted(d for _, d in first.degree()),
            sorted(d for _, d in second.degree()),
        )
        self.assertFalse(nx.vf2pp_is_isomorphic(first, second))
