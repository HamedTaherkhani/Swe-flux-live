import io
import random
import unittest

import networkx as nx
from networkx.readwrite.gml import literal_destringizer, literal_stringizer


def _dump(G, stringizer=None):
    buf = io.BytesIO()
    nx.write_gml(G, buf, stringizer=stringizer)
    return buf.getvalue().decode("ascii")


class TestGmlWriterScenarios(unittest.TestCase):
    def test_path_with_float_weights(self):
        rng = random.Random(11)
        G = nx.path_graph(9)
        for n in G:
            G.nodes[n]["weight"] = rng.choice([0.5, 1e22, 3.0, float("inf"), 2.5e-7])
        for u, v in G.edges:
            G.edges[u, v]["cap"] = (u * 7 + v) % 5
        text = _dump(G)
        self.assertTrue(text.startswith("graph ["))
        self.assertEqual(text.count("edge ["), G.number_of_edges())

    def test_directed_nested_graph_attributes(self):
        G = nx.DiGraph()
        G.graph["directed"] = 1
        G.graph["node"] = "ignored"
        G.graph["meta"] = {
            "level%d" % i: {"depth": i, "name": "x" * i} for i in range(1, 4)
        }
        G.graph["title"] = "net & \"stuff\""
        nx.add_cycle(G, range(6))
        lines = list(nx.generate_gml(G))
        self.assertIn("  directed 1", lines)
        self.assertEqual(sum(1 for ln in lines if ln.strip() == "]"), 6 + 6 + 4 + 1)

    def test_multigraph_with_keys_and_lists(self):
        G = nx.MultiGraph()
        for i in range(5):
            G.add_edge(i % 3, (i + 1) % 3, key=i, hops=[i, i + 1, i * 2][: i % 3 + 1])
        text = _dump(G)
        self.assertIn("multigraph 1", text)
        self.assertEqual(text.count("key "), G.number_of_edges())

    def test_unicode_and_quotes_in_labels(self):
        words = ["café", "naïveè", 'say "hi"', "a&b&c", "plain", "πρ"]
        G = nx.Graph()
        for a, b in zip(words, words[1:]):
            G.add_edge(a, b, note=a[::-1])
        text = _dump(G)
        self.assertNotIn("é", text)
        self.assertIn("&#", text)

    def test_tuple_nodes(self):
        G = nx.grid_2d_graph(2, 3)
        for n in G:
            G.nodes[n]["sum"] = sum(n)
        lines = list(nx.generate_gml(G))
        self.assertEqual(sum(1 for ln in lines if "label" in ln), len(G))

    def test_literal_values_via_custom_converter(self):
        G = nx.Graph()
        G.add_node("a", data=[1, (2,), {"k": None}], flag={(1, (2, 3)), (4, 5, (6, (7,)))})
        G.add_node("b", data=(True, False, "q"), other=())
        G.add_node("c", data=complex(1, 2), more=b"xy")
        G.add_edge("a", "b", payload={"x": [1, 2], "y": ("z", 1.5)})
        G.add_edge("b", "c", payload=None)
        text = _dump(G, stringizer=literal_stringizer)
        self.assertEqual(text.count("node ["), 3)

    def test_large_ints_and_bools(self):
        G = nx.Graph()
        vals = [2**31, -(2**31) - 1, 2**31 - 1, True, False, 0, -5, 10**12]
        for i, v in enumerate(vals):
            G.add_node(i, v=v, label_like=i % 2 == 0)
        G.add_node(True)
        text = _dump(G)
        self.assertEqual(text.count("node ["), len(G))

    def test_invalid_key_rejected(self):
        G = nx.Graph()
        G.add_node(0, good=1)
        G.add_node(1, **{"9bad": 2})
        with self.assertRaises(nx.NetworkXError):
            _dump(G)

    def test_non_string_key_rejected(self):
        G = nx.Graph()
        G.add_edge(0, 1, ok=1.0)
        G.edges[0, 1][7] = "seven"
        with self.assertRaises(nx.NetworkXError):
            list(nx.generate_gml(G))

    def test_unconvertible_value(self):
        G = nx.Graph()
        G.add_node("n", items=[1, 2, object()])
        with self.assertRaises(nx.NetworkXError):
            _dump(G, stringizer=literal_stringizer)
        G2 = nx.Graph()
        G2.add_node("m", thing=object())
        with self.assertRaises(nx.NetworkXError):
            _dump(G2)

    def test_empty_and_single_lists_roundtrip(self):
        G = nx.Graph()
        G.add_node("p", empty=[], single=["only"], many=["u", "v", "w"])
        G.add_node("q", empty=(), single=[4.25])
        G.add_edge("p", "q", tag="\u00e9&e")
        text = _dump(G)
        H = nx.parse_gml(text)
        self.assertEqual(sorted(H.nodes), ["p", "q"])
        self.assertEqual(H.nodes["p"]["single"], ["only"])

    def test_random_graph_literal_roundtrip(self):
        rng = random.Random(5)
        G = nx.gnm_random_graph(7, 9, seed=3)
        for n in G:
            G.nodes[n]["vec"] = tuple(rng.randint(0, 9) for _ in range(rng.randint(0, 3)))
        for u, v in G.edges:
            G.edges[u, v]["w"] = rng.random() < 0.5
        text = _dump(G, stringizer=literal_stringizer)
        H = nx.parse_gml(text, destringizer=literal_destringizer)
        self.assertEqual(H.number_of_edges(), G.number_of_edges())
        self.assertEqual(sorted(H.nodes), sorted(G.nodes))


if __name__ == "__main__":
    unittest.main()
