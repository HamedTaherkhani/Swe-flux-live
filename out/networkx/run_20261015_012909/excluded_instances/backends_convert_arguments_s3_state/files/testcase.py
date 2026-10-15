import random
import unittest

import networkx as nx
from networkx.algorithms.connectivity import (
    build_auxiliary_node_connectivity,
    local_edge_connectivity,
    local_node_connectivity,
)
from networkx.classes.tests.dispatch_interface import convert
from networkx.utils import backends as nxb

LOOPBACK = "nx_" + "loopback"


def _attr_name(rng, prefix):
    return f"{prefix}{rng.randrange(10, 99)}{chr(97 + rng.randrange(26))}"


class TestLoopbackDispatchBatch(unittest.TestCase):
    def setUp(self):
        from importlib.metadata import entry_points

        ep = entry_points(name=LOOPBACK, group="networkx.backends")[LOOPBACK]
        self._saved = (
            dict(nxb.backends),
            dict(nxb.backend_info),
            nxb._dispatchable.__call__,
            nx.config.cache_converted_graphs,
        )
        nxb.backends[LOOPBACK] = ep
        nxb.backend_info[LOOPBACK] = {}
        nxb._dispatchable.__call__ = nxb._dispatchable._call_if_any_backends_installed
        nx.config.cache_converted_graphs = False

    def tearDown(self):
        backends, info, call, cache = self._saved
        nxb.backends.clear()
        nxb.backends.update(backends)
        nxb.backend_info.clear()
        nxb.backend_info.update(info)
        nxb._dispatchable.__call__ = call
        nx.config.cache_converted_graphs = cache

    def test_batch_of_dispatched_calls(self):
        rng = random.Random(8939)
        names = {
            key: _attr_name(rng, key[0])
            for key in ["weight", "capacity", "demand", "label", "flow"]
        }
        default_weight = rng.randrange(2, 9)
        default_label = _attr_name(rng, "z")

        def rand_graph(n, p, directed=False):
            G = nx.gnp_random_graph(n, p, seed=rng.randrange(1000), directed=directed)
            for u, v in G.edges:
                G[u][v][names["weight"]] = rng.randrange(1, 20)
                G[u][v][names["capacity"]] = rng.randrange(1, 9)
            for n_ in G:
                G.nodes[n_][names["label"]] = rng.choice("abc")
            return G

        def dag(n):
            D = nx.DiGraph()
            D.add_nodes_from(range(n))
            for u in range(n):
                for v in range(u + 1, n):
                    if rng.random() < 0.3:
                        D.add_edge(u, v, **{names["weight"]: rng.randrange(1, 15)})
            return D

        G1 = rand_graph(12, 0.35)
        G2 = nx.relabel_nodes(G1, {n: (n * 7) % 12 for n in G1})
        Gd = rand_graph(10, 0.4, directed=True)
        D = dag(11)
        C = nx.connected_watts_strogatz_graph(14, 4, 0.3, seed=rng.randrange(1000))
        aux = build_auxiliary_node_connectivity(C)
        lb = convert(G1)

        def far(s):
            return max(n for n in C if n != s and n not in C[s])

        R = nx.algorithms.flow.edmonds_karp(Gd, 0, 9, capacity=names["capacity"])

        specs = [
            ("mcf", lambda be: nx.min_cost_flow_cost(
                Gd, demand=names["demand"], capacity=names["capacity"],
                weight=names["weight"], backend=be)),
            ("iso_em", lambda be: nx.is_isomorphic(
                G1, G2, edge_match=lambda a, b: a == b, backend=be)),
            ("iso", lambda be: nx.is_isomorphic(G1, G2, backend=be)),
            ("vf2pp", lambda be: nx.vf2pp_is_isomorphic(
                G1, G2, node_label=names["label"], default_label=default_label,
                backend=be)),
            ("spl", lambda be: nx.shortest_path_length(
                G1, 0, max(nx.node_connected_component(G1, 0)),
                weight=names["weight"], backend=be)),
            ("astar", lambda be: nx.astar_path_length(
                G1, 0, max(nx.node_connected_component(G1, 0)),
                weight=names["weight"], backend=be)),
            ("union", lambda be: nx.union_all(
                [G1, nx.relabel_nodes(G2, lambda n: n + 100)], backend=be
            ).number_of_edges()),
            ("hits", lambda be: round(max(nx.hits(C, backend=be)[0].values()), 6)),
            ("iso_mix", lambda be: nx.is_isomorphic(
                lb, G2, node_match=lambda a, b: a == b, backend=be)),
            ("dlpl", lambda be: nx.dag_longest_path_length(
                D, weight=names["weight"], default_weight=default_weight,
                backend=be)),
            ("lnc", lambda be: local_node_connectivity(C, 0, far(0), backend=be)),
            ("lnc_aux", lambda be: local_node_connectivity(
                C, 1, far(1), auxiliary=aux, backend=be)),
            ("lec", lambda be: local_edge_connectivity(C, 2, 11, backend=be)),
            ("bfd", lambda be: sum(
                sum(v.values()) for v in nx.algorithms.flow.build_flow_dict(
                    Gd, R, backend=be).values())),
        ]
        order = [s for s in specs for _ in range(1 + (len(s[0]) % 2))]
        rng.shuffle(order)

        expected = {key: fn("networkx") for key, fn in specs}
        seen = []
        for key, fn in order:
            if key == "lnc_aux":
                # Edge capacities of `auxiliary` are not preserved on conversion
                with self.assertRaises(nx.NetworkXUnbounded):
                    fn(LOOPBACK)
            else:
                self.assertEqual(fn(LOOPBACK), expected[key], key)
            seen.append(key)
        self.assertEqual(len(seen), len(order))
        self.assertGreater(len(order), 15)


if __name__ == "__main__":
    unittest.main()
