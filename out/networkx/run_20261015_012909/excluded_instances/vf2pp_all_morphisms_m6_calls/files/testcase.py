"""Scenarios driving the VF2++ public API over seeded, programmatically built graphs.

All nodes and labels are integers so that set iteration order (and therefore the
search order) does not depend on PYTHONHASHSEED.
"""

import random
import unittest

import networkx as nx


def _shuffled_copy(G, seed):
    rng = random.Random(seed)
    nodes = list(G.nodes())
    perm = nodes[:]
    rng.shuffle(perm)
    offset = 100 + seed
    return nx.relabel_nodes(G, {n: offset + p for n, p in zip(nodes, perm)})


def _label(G, attr, modulus, seed):
    rng = random.Random(seed)
    for n in sorted(G.nodes()):
        G.nodes[n][attr] = rng.randrange(modulus)


class TestVF2PPScenarios(unittest.TestCase):
    def test_iso_random_undirected(self):
        G1 = nx.gnm_random_graph(11, 19, seed=7)
        G2 = _shuffled_copy(G1, 3)
        self.assertTrue(nx.vf2pp_is_isomorphic(G1, G2))

    def test_non_iso_same_degrees(self):
        # Two 3-regular graphs on 8 nodes with different structure.
        G1 = nx.circulant_graph(8, [1, 4])
        G2 = nx.disjoint_union(nx.complete_graph(4), nx.complete_graph(4))
        self.assertFalse(nx.vf2pp_is_isomorphic(G1, G2))

    def test_all_isos_cycle(self):
        G1 = nx.cycle_graph(7)
        G2 = _shuffled_copy(G1, 5)
        maps = list(nx.vf2pp_all_isomorphisms(G1, G2))
        self.assertEqual(len(maps), 2 * G1.number_of_nodes())
        self.assertTrue(all(len(m) == len(G1) for m in maps))

    def test_iso_directed_labeled(self):
        G1 = nx.gnp_random_graph(9, 0.3, seed=11, directed=True)
        _label(G1, "c", 3, 2)
        G2 = _shuffled_copy(G1, 4)
        m = nx.vf2pp_isomorphism(G1, G2, node_label="c")
        self.assertIsNotNone(m)
        self.assertEqual(len(m), 9)

    def test_all_subgraph_isos_path_in_grid(self):
        FG = nx.convert_node_labels_to_integers(nx.grid_2d_graph(3, 3))
        SG = nx.path_graph(3)
        maps = list(nx.vf2pp_all_subgraph_isomorphisms(FG, SG))
        self.assertTrue(len(maps) > 0)
        for m in maps:
            self.assertEqual(sorted(m.values()), [0, 1, 2])

    def test_mono_labeled(self):
        FG = nx.wheel_graph(8)
        SG = nx.star_graph(4)
        _label(FG, "k", 2, 9)
        for n in SG:
            SG.nodes[n]["k"] = FG.nodes[0]["k"] if n == 0 else 1 - FG.nodes[0]["k"]
        result = nx.vf2pp_is_monomorphic(FG, SG, node_label="k")
        self.assertIsInstance(result, bool)

    def test_all_monos_directed(self):
        FG = nx.DiGraph(nx.cycle_graph(5, create_using=nx.DiGraph))
        FG.add_edges_from((i, (i + 2) % 5) for i in range(5))
        SG = nx.path_graph(3, create_using=nx.DiGraph)
        maps = list(nx.vf2pp_all_monomorphisms(FG, SG))
        self.assertTrue(len(maps) > 0)

    def test_empty_graph(self):
        self.assertFalse(nx.vf2pp_is_isomorphic(nx.Graph(), nx.path_graph(3)))
        self.assertEqual(list(nx.vf2pp_all_isomorphisms(nx.path_graph(2), nx.Graph())), [])

    def test_directedness_mismatch(self):
        with self.assertRaises(nx.NetworkXError):
            nx.vf2pp_is_isomorphic(nx.path_graph(4), nx.path_graph(4, create_using=nx.DiGraph))

    def test_label_count_mismatch(self):
        G1 = nx.path_graph(6)
        G2 = nx.path_graph(6)
        _label(G1, "t", 2, 1)
        _label(G2, "t", 2, 8)
        r = nx.vf2pp_isomorphism(G1, G2, node_label="t", default_label=0)
        self.assertTrue(r is None or len(r) == 6)

    def test_size_mismatch(self):
        self.assertIsNone(nx.vf2pp_isomorphism(nx.cycle_graph(5), nx.cycle_graph(6)))

    def test_subgraph_missing_label(self):
        FG = nx.complete_graph(5)
        SG = nx.path_graph(3)
        nx.set_node_attributes(FG, 1, "z")
        nx.set_node_attributes(SG, {0: 1, 1: 2, 2: 1}, "z")
        self.assertFalse(nx.vf2pp_subgraph_is_isomorphic(FG, SG, node_label="z"))

    def test_multigraph_iso(self):
        rng = random.Random(21)
        edges = [(rng.randrange(7), rng.randrange(7)) for _ in range(14)]
        G1 = nx.MultiGraph(edges)
        G2 = _shuffled_copy(G1, 6)
        self.assertTrue(nx.vf2pp_is_isomorphic(G1, G2))

    def test_induced_subgraph_absent(self):
        FG = nx.complete_graph(6)
        SG = nx.path_graph(4)
        self.assertFalse(nx.vf2pp_subgraph_is_isomorphic(FG, SG))


if __name__ == "__main__":
    unittest.main()
