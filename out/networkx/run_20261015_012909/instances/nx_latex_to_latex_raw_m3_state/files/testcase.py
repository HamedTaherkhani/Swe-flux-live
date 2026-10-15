import io
import random
import unittest

import networkx as nx

COLORS = ["red", "blue", "teal", "gray"]
STYLES = ["dashed", "thick", "dotted"]
BENDS = ["bend left", "bend right"]
LOOPS = ["loop above", "loop below", "out=90,in=0"]


def _attach_grid_pos(G):
    for i, n in enumerate(sorted(G, key=str)):
        G.nodes[n]["pos"] = (i % 4 + 0.12345 * i, i // 4 - 0.5)
    return G


class TestLatexEdgeOptions(unittest.TestCase):
    def test_directed_random_options(self):
        rng = random.Random(11)
        G = nx.gnp_random_graph(7, 0.35, seed=3, directed=True)
        for n in (0, 4):
            G.add_edge(n, n)
        for u, v in sorted(G.edges):
            r = rng.random()
            if r < 0.4:
                G.edges[u, v]["edge_options"] = f"[{rng.choice(COLORS)}]"
            elif r < 0.7:
                G.edges[u, v]["edge_options"] = (
                    rng.choice(STYLES) + "," + rng.choice(COLORS)
                )
        _attach_grid_pos(G)
        out = nx.to_latex(G, as_document=False)
        self.assertEqual(out.count("\\draw["), sum(
            1 for u, v in G.edges if "edge_options" in G.edges[u, v] or u == v
        ))

    def test_undirected_reversed_dict_keys(self):
        G = nx.cycle_graph(9)
        G.add_edge(2, 6)
        opts = {}
        for k, (u, v) in enumerate(sorted(G.edges)):
            key = (v, u) if k % 3 == 1 else (u, v)
            opts[key] = BENDS[k % 2] + ("," + COLORS[k % 4] if k % 4 == 0 else "")
        pos = {n: (n * 0.7, (n * n) % 5) for n in G}
        out = nx.to_latex(G, pos=pos, edge_options=opts)
        self.assertIn("\\begin{document}", out)

    def test_selfloops_explicit_and_implicit(self):
        G = nx.DiGraph()
        G.add_nodes_from(range(6))
        for n in range(6):
            G.add_edge(n, n)
            G.add_edge(n, (n * 2 + 1) % 6)
        for n in range(6):
            if n % 3 == 0:
                G.edges[n, n]["edge_options"] = "[" + LOOPS[n % 3] + "]"
            elif n % 3 == 1:
                G.edges[n, n]["edge_options"] = COLORS[n % 4]
        _attach_grid_pos(G)
        out = nx.to_latex(G, as_document=False)
        self.assertGreaterEqual(out.count("loop"), 6)

    def test_subfigures_bunch(self):
        graphs = []
        for s in range(3):
            H = nx.path_graph(4 + s)
            for u, v in H.edges:
                if (u + s) % 2 == 0:
                    H.edges[u, v]["edge_options"] = STYLES[(u + s) % 3]
            if s == 2:
                H.add_edge(1, 1, edge_options=STYLES[2] + "," + LOOPS[1])
            _attach_grid_pos(H)
            graphs.append(H)
        out = nx.to_latex(
            graphs, sub_captions=[f"c{i}" for i in range(3)], n_rows=3
        )
        self.assertEqual(out.count("\\begin{subfigure}"), 3)

    def test_write_latex_stringio(self):
        G = nx.star_graph(5)
        G.add_edge(0, 0)
        for u, v in G.edges:
            G.edges[u, v]["style"] = f"{COLORS[(u + v) % 4]}!{10 * (u + v)}"
        _attach_grid_pos(G)
        buf = io.StringIO()
        nx.write_latex(G, buf, edge_options="style", as_document=False)
        self.assertIn("\\end{tikzpicture}", buf.getvalue())

    def test_non_string_options(self):
        G = nx.DiGraph()
        for k in range(5):
            G.add_edge(k, k + 1, edge_options=k * k + 1)
        G.add_edge(5, 5, edge_options=2.5)
        G.add_edge(3, 3, edge_options=None)
        _attach_grid_pos(G)
        out = nx.to_latex(G, as_document=False)
        self.assertIn("\\begin{scope}[->]", out)

    def test_nested_brackets_and_spaces(self):
        G = nx.Graph()
        G.add_edges_from([(0, 1), (1, 2), (2, 0), (2, 2), (1, 1)])
        decor = {
            (0, 1): "[[" + COLORS[0] + "]]",
            (1, 2): " [" + STYLES[1] + "] ",
            (0, 2): "[" + COLORS[1] + "][",
            (2, 2): "]" + BENDS[0] + "[",
            (1, 1): "[]",
        }
        nx.set_edge_attributes(G, decor, "edge_options")
        _attach_grid_pos(G)
        out = nx.to_latex(G, as_document=False)
        self.assertEqual(out.count("\\draw["), 5)

    def test_missing_position_raises(self):
        G = nx.path_graph(5)
        _attach_grid_pos(G)
        G.add_edge(4, 5)
        with self.assertRaises(nx.NetworkXError):
            nx.to_latex(G)

    def test_bad_position_shape_raises(self):
        G = nx.path_graph(4)
        pos = {n: (n, n + 1) for n in G}
        pos[2] = (1, 2, 3)
        with self.assertRaises(nx.NetworkXError):
            nx.to_latex(G, pos=pos)

    def test_multigraph_rejected(self):
        G = nx.MultiGraph([(0, 1), (0, 1)])
        _attach_grid_pos(G)
        with self.assertRaises(nx.NetworkXNotImplemented):
            nx.to_latex(G)

    def test_label_options_only_circular(self):
        G = nx.wheel_graph(6)
        G.add_edge(3, 3)
        for u, v in G.edges:
            G.edges[u, v]["edge_label"] = str(u * v)
            if (u + v) % 2:
                G.edges[u, v]["edge_label_options"] = "[sloped]"
        out = nx.to_latex(G, pos={}, as_document=False)
        self.assertIn(":2)", out)

    def test_dict_options_with_default_edge_options(self):
        rng = random.Random(5)
        G = nx.random_regular_graph(3, 8, seed=2)
        G.add_edge(7, 7)
        G.add_edge(1, 1)
        opts = {}
        for e in G.edges:
            pick = rng.randrange(4)
            if pick == 0:
                opts[e] = LOOPS[rng.randrange(3)]
            elif pick == 1:
                opts[e] = rng.choice(COLORS) + "," + rng.choice(BENDS)
            elif pick == 2:
                opts[e] = ""
        pos = nx.circular_layout(G)
        out = nx.to_latex(
            G, pos=pos, edge_options=opts, default_edge_options="thin",
            as_document=False,
        )
        self.assertIn("[-,thin]", out)
