import random
import unittest
from xml.etree.ElementTree import Element, SubElement

import networkx as nx
from networkx.readwrite.gexf import GEXFReader


def build_gexf(
    ns,
    rng,
    n_nodes,
    n_edges,
    directed=False,
    allow_parallel=False,
    attr_classes=(),
    meta=None,
    graph_attrs=None,
    with_nodes=True,
    with_edges=True,
):
    """Build a (meta, graph) element pair in namespace ``ns``.

    ``attr_classes`` is a sequence of attribute-class names; one
    ``<attributes>`` block is emitted per entry, in order.
    """
    q = lambda tag: f"{{{ns}}}{tag}"  # noqa: E731

    meta_el = None
    if meta is not None:
        meta_el = Element(q("meta"))
        for key in sorted(meta):
            sub = SubElement(meta_el, q(key))
            sub.text = meta[key]

    graph = Element(q("graph"))
    if directed:
        graph.set("defaultedgetype", "directed")
    elif rng.random() < 0.5:
        graph.set("defaultedgetype", "undirected")
    for key, val in (graph_attrs or {}).items():
        graph.set(key, val)

    node_ids = []
    edge_ids = []
    for idx, cls in enumerate(attr_classes):
        block = SubElement(graph, q("attributes"), {"class": cls, "mode": "static"})
        for j in range(rng.randint(1, 3)):
            aid = f"{cls[0]}{idx}_{j}"
            att = SubElement(
                block, q("attribute"), {"id": aid, "title": f"t{aid}", "type": "integer"}
            )
            if (idx + j) % 2 == 0:
                SubElement(att, q("default")).text = str(rng.randint(0, 9))
            if cls == "node":
                node_ids.append(aid)
            elif cls == "edge":
                edge_ids.append(aid)

    if with_nodes:
        nodes = SubElement(graph, q("nodes"))
        for i in range(n_nodes):
            nd = SubElement(nodes, q("node"), {"id": str(i), "label": f"n{i}"})
            if node_ids and rng.random() < 0.6:
                avs = SubElement(nd, q("attvalues"))
                SubElement(
                    avs,
                    q("attvalue"),
                    {"for": rng.choice(node_ids), "value": str(rng.randint(0, 99))},
                )

    if with_edges:
        edges = SubElement(graph, q("edges"))
        seen = set()
        made = 0
        attempts = 0
        while made < n_edges and attempts < 50 * (n_edges + 1):
            attempts += 1
            u = rng.randrange(n_nodes)
            v = rng.randrange(n_nodes)
            if u == v:
                continue
            key = (u, v) if directed else tuple(sorted((u, v)))
            if key in seen and not allow_parallel:
                continue
            seen.add(key)
            e = SubElement(
                edges,
                q("edge"),
                {"id": str(made), "source": str(u), "target": str(v)},
            )
            if rng.random() < 0.3:
                e.set("weight", str(round(rng.uniform(0.5, 3.0), 2)))
            if edge_ids and rng.random() < 0.5:
                avs = SubElement(e, q("attvalues"))
                SubElement(
                    avs,
                    q("attvalue"),
                    {"for": rng.choice(edge_ids), "value": str(rng.randint(0, 99))},
                )
            made += 1
    return meta_el, graph


class TestGEXFMakeGraph(unittest.TestCase):
    def _read(self, reader, meta_el, graph_el):
        return reader.make_graph(graph_el, meta_xml=meta_el)

    def test_undirected_simple_with_full_meta(self):
        rng = random.Random(11)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=18,
            n_edges=24,
            attr_classes=("node",),
            meta={"description": "random", "keywords": "kw"},
            graph_attrs={"name": "alpha"},
        )
        G = self._read(reader, meta_el, g)
        self.assertFalse(G.is_multigraph())
        self.assertEqual(G.number_of_nodes(), 18)
        self.assertIn("description", G.graph)

    def test_directed_with_parallel_edges(self):
        rng = random.Random(22)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=6,
            n_edges=25,
            directed=True,
            allow_parallel=True,
            attr_classes=("edge", "node"),
        )
        G = self._read(reader, meta_el, g)
        self.assertTrue(G.is_multigraph())
        self.assertTrue(G.is_directed())

    def test_directed_simple_dynamic_dates(self):
        rng = random.Random(33)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=14,
            n_edges=16,
            directed=True,
            meta={"keywords": "dyn"},
            graph_attrs={
                "mode": "dynamic",
                "timeformat": "date",
                "start": "2020-01-01",
                "end": "2021-01-01",
            },
        )
        G = self._read(reader, meta_el, g)
        self.assertIsInstance(G, nx.DiGraph)
        self.assertFalse(G.is_multigraph())
        self.assertEqual(reader.timeformat, "string")

    def test_unknown_attribute_class_raises(self):
        rng = random.Random(44)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=5,
            n_edges=4,
            attr_classes=("node", "edge", "node", "graph", "edge"),
            meta={"description": "bad"},
        )
        with self.assertRaises(nx.NetworkXError):
            self._read(reader, meta_el, g)

    def test_many_attribute_blocks(self):
        rng = random.Random(55)
        reader = GEXFReader()
        classes = tuple("node" if (i * 7) % 3 else "edge" for i in range(7))
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=12,
            n_edges=15,
            attr_classes=classes,
            graph_attrs={"name": "blocks", "mode": "static"},
        )
        G = self._read(reader, meta_el, g)
        self.assertIn("node_default", G.graph)
        self.assertIn("edge_default", G.graph)

    def test_empty_graph_no_containers(self):
        rng = random.Random(66)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=0,
            n_edges=0,
            with_nodes=False,
            with_edges=False,
            graph_attrs={"name": "", "end": "9"},
        )
        G = self._read(reader, meta_el, g)
        self.assertEqual(len(G), 0)
        self.assertNotIn("name", G.graph)

    def test_nodes_only_with_meta_keywords(self):
        rng = random.Random(77)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=21,
            n_edges=0,
            with_edges=False,
            attr_classes=("node", "node"),
            meta={"keywords": "only"},
        )
        G = self._read(reader, meta_el, g)
        self.assertEqual(G.number_of_edges(), 0)
        self.assertEqual(G.number_of_nodes(), 21)

    def test_reused_reader_sticky_multigraph_flag(self):
        rng = random.Random(88)
        reader = GEXFReader()
        kinds = []
        for i in range(5):
            meta_el, g = build_gexf(
                reader.NS_GEXF,
                rng,
                n_nodes=4 + i,
                n_edges=3 + 2 * i,
                directed=bool(i % 2),
                allow_parallel=(i == 2),
                attr_classes=("edge",) * (i % 3),
            )
            kinds.append(self._read(reader, meta_el, g).is_multigraph())
        self.assertEqual(len(kinds), 5)
        self.assertFalse(reader.simple_graph)

    def test_fresh_readers_random_mix(self):
        rng = random.Random(99)
        sizes = [rng.randint(3, 9) for _ in range(6)]
        results = []
        for k, n in enumerate(sizes):
            reader = GEXFReader()
            directed = rng.random() < 0.5
            meta = {"description": f"d{k}"} if k % 3 == 0 else None
            meta_el, g = build_gexf(
                reader.NS_GEXF,
                rng,
                n_nodes=n,
                n_edges=n + k,
                directed=directed,
                allow_parallel=rng.random() < 0.4,
                attr_classes=("node",) if k % 2 else ("edge", "node"),
                meta=meta,
            )
            results.append(type(self._read(reader, meta_el, g)).__name__)
        self.assertEqual(len(results), len(sizes))

    def test_version_11_reader(self):
        rng = random.Random(1010)
        reader = GEXFReader(version="1.1draft")
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=16,
            n_edges=20,
            directed=True,
            attr_classes=("edge",),
            meta={"description": "v11", "keywords": "old"},
            graph_attrs={"start": "0", "timeformat": "double"},
        )
        G = self._read(reader, meta_el, g)
        self.assertTrue(G.is_directed())
        self.assertEqual(reader.timeformat, "double")

    def test_edges_without_nodes_element(self):
        rng = random.Random(1111)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=10,
            n_edges=13,
            with_nodes=False,
            allow_parallel=True,
            attr_classes=("edge", "edge"),
            graph_attrs={"name": "edgesonly"},
        )
        G = self._read(reader, meta_el, g)
        self.assertGreater(G.number_of_edges(), 0)

    def test_meta_without_known_children(self):
        rng = random.Random(1212)
        reader = GEXFReader()
        meta_el, g = build_gexf(
            reader.NS_GEXF,
            rng,
            n_nodes=9,
            n_edges=11,
            meta={"creator": "someone"},
            graph_attrs={"mode": "slice"},
        )
        G = self._read(reader, meta_el, g)
        self.assertNotIn("description", G.graph)
        self.assertNotIn("keywords", G.graph)


if __name__ == "__main__":
    unittest.main()
