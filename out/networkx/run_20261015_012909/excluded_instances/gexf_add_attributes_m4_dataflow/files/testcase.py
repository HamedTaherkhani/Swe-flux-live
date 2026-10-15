import io
import random
import unittest

import numpy as np

import networkx as nx


def _render(G, version="1.2draft"):
    return "\n".join(nx.generate_gexf(G, version=version))


def _dump(G, version="1.2draft"):
    buf = io.BytesIO()
    nx.write_gexf(G, buf, version=version)
    return buf.getvalue().decode("utf-8")


class TestGexfAttributeWriting(unittest.TestCase):
    def test_static_scalar_mix(self):
        rng = random.Random(11)
        G = nx.path_graph(9)
        specials = [float("inf"), float("nan"), float("-inf"), 2.5]
        for n in G:
            r = rng.randrange(4)
            if r == 0:
                G.nodes[n]["score"] = rng.randint(-5, 50)
            elif r == 1:
                G.nodes[n]["score"] = specials[n % len(specials)]
            elif r == 2:
                G.nodes[n]["flag"] = rng.random() < 0.5
            if n % 3 == 0:
                G.nodes[n]["tag"] = f"t{rng.randint(0, 9)}"
        for u, v in G.edges():
            if (u + v) % 4 == 1:
                G.edges[u, v]["weight"] = u + v
        out = _render(G)
        self.assertIn("<nodes>", out)
        self.assertEqual(out.count("<node "), 9)

    def test_multigraph_keys_renamed(self):
        rng = random.Random(23)
        G = nx.MultiGraph()
        G.add_nodes_from(range(5))
        for i in range(7):
            u, v = rng.sample(range(5), 2)
            if i % 2:
                G.add_edge(u, v, key=f"k{i}", w=rng.randint(1, 9))
            else:
                G.add_edge(u, v, key=i)
        out = _render(G)
        self.assertIn("networkx_key", out)
        self.assertEqual(out.count("<edge "), 7)

    def test_dynamic_lists_with_and_without_times(self):
        rng = random.Random(5)
        G = nx.Graph()
        for n in range(6):
            series = []
            for j in range(rng.randint(1, 4)):
                if (n + j) % 3 == 0:
                    series.append((rng.randint(0, 99), None, None))
                else:
                    series.append((rng.randint(0, 99), j, j + 1))
            G.add_node(n, hist=series)
            if n % 2 == 0:
                G.nodes[n]["kind"] = "even"
        out = _render(G)
        self.assertIn("attvalue", out)

    def test_static_then_untimed_list(self):
        G = nx.Graph()
        for n in range(4):
            data = {}
            data["a" + str(n % 2)] = n * 1.5
            data["series"] = [(n + i, None, None) for i in range(n + 1)]
            if n >= 2:
                data["later"] = [(str(n), n, None), (str(n + 1), None, n + 3)]
            G.add_node(n, **data)
        out = _render(G)
        self.assertGreater(out.count("<attvalue "), 10)

    def test_numpy_values(self):
        G = nx.Graph()
        vals = [np.float64(np.inf), np.float64(1.25), np.int64(7), np.float32(-np.inf)]
        for i, val in enumerate(vals):
            G.add_node(i, x=val, y=float(i) if i % 2 else int(i))
        G.add_edge(0, 1, w=np.float64(np.nan))
        G.add_edge(2, 3, w=float("nan"))
        out = _render(G)
        self.assertIn("NaN", out)

    def test_unsupported_tuple_value(self):
        G = nx.Graph()
        G.add_node("a", ok=3)
        G.add_node("b", ok=4, bad=(1, 2))
        with self.assertRaises(TypeError):
            _render(G)

    def test_conflicting_attribute_types(self):
        G = nx.Graph()
        G.add_node(0, val=1, other="x")
        G.add_node(1, other="y", val="one")
        with self.assertRaises(ValueError):
            _dump(G)

    def test_bool_and_dict_values_with_defaults(self):
        rng = random.Random(77)
        G = nx.DiGraph(node_default={"on": False}, edge_default={"meta": "none"})
        for i in range(6):
            G.add_node(i, on=rng.random() < 0.5)
            if i % 3 == 2:
                G.nodes[i]["cfg"] = {"i": i}
        for i in range(5):
            G.add_edge(i, i + 1, meta={"hop": i}, ok=[(i % 2 == 0, i, i + 2)])
        out = _dump(G)
        self.assertIn("<default>", out)

    def test_version_11_slices(self):
        G = nx.Graph()
        for i in range(4):
            G.add_node(i, slices=[(i, i + 1)], level=i * i, label=f"L{i}")
        G.add_edge(0, 1, slices=[(0, 1)], key="edge-key")
        G.add_edge(1, 2, cost=2.0)
        out = _render(G, version="1.1draft")
        self.assertIn("slices", out)

    def test_empty_list_and_float_times(self):
        G = nx.Graph()
        G.add_node(0, hist=[], z=0)
        G.add_node(1, hist=[(0.5, 0.0, 1.0), (1.5, 1.0, 2.0)], z=[(1, None, None)])
        G.add_node(2, z=[(2.0, None, None), (3, None, 4.5)])
        out = _render(G)
        self.assertIn("dynamic", out)

    def test_random_attribute_graph(self):
        rng = random.Random(2024)
        G = nx.gnm_random_graph(10, 14, seed=3)
        pool = ["alpha", "beta", "gamma"]
        for n in G:
            for name in pool:
                if rng.random() < 0.45:
                    G.nodes[n][name] = rng.choice([rng.randint(0, 9), rng.random(), "s"])
        for u, v in G.edges():
            if rng.random() < 0.5:
                G.edges[u, v]["cap"] = rng.randint(1, 20)
            if rng.random() < 0.3:
                G.edges[u, v]["note"] = [(rng.choice(pool), None, None)]
        try:
            out = _render(G)
        except ValueError:
            out = ""
        self.assertIsInstance(out, str)

    def test_viz_and_spells_stripped(self):
        G = nx.Graph()
        for i in range(5):
            G.add_node(
                i,
                viz={"size": i + 1},
                spells=[(i, i + 2)],
                start=i,
                weight=i / 2 if i % 2 else i,
            )
        G.add_edge(0, 4, start=0, end=3, viz={"thickness": 2})
        G.add_edge(1, 3, start=1, label="e13", rank=[("hi", "2020-01-01", None)])
        out = _render(G)
        self.assertIn("spells", out)


if __name__ == "__main__":
    unittest.main()
