import io
import random
import unittest

import networkx as nx


def build_graph():
    rng = random.Random(8939)
    G = nx.MultiGraph(name="mesh", revision=3)
    for n in range(18):
        attrs = {}
        if n % 4 != 1:
            attrs["tier"] = n // 5
        if rng.random() < 0.4:
            attrs["tag"] = f"n{n}"
        G.add_node(n, **attrs)
    for step in range(40):
        u = rng.randrange(18)
        v = rng.randrange(18)
        attrs = {}
        if (u * v) % 3 != 0:
            attrs["weight"] = round(rng.uniform(0.5, 4.0), 2)
        if (u + v) % 5 == 0:
            attrs["color"] = rng.choice(["red", "blue", "green"])
        if step % 7 == 3:
            attrs["capacity"] = step
        key = step % 3 if rng.random() < 0.5 else None
        if key is None:
            G.add_edge(u, v, **attrs)
        else:
            # Re-adding an existing (u, v, key) updates its data in place.
            G.add_edge(u, v, key=key, **attrs)
    return G


class TestGraphMLLxmlMultigraph(unittest.TestCase):
    def test_write_multigraph_with_mixed_edge_data(self):
        G = build_graph()
        buf = io.BytesIO()
        nx.write_graphml(G, buf)
        text = buf.getvalue().decode("utf-8")
        self.assertIn("<graphml", text)
        self.assertIn('edgedefault="undirected"', text)

        H = nx.read_graphml(io.BytesIO(buf.getvalue()), node_type=int)
        self.assertTrue(H.is_multigraph())
        self.assertEqual(H.number_of_nodes(), G.number_of_nodes())
        self.assertEqual(H.number_of_edges(), G.number_of_edges())


if __name__ == "__main__":
    unittest.main()
