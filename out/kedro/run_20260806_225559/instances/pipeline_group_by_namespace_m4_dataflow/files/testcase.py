"""Deterministic exercise of kedro's namespace-based node grouping.

Builds three pipelines programmatically (layered mesh, mixed bare/namespaced
nodes, and a deduplicating diamond) and asks each one for its grouping via
the public ``Pipeline.group_nodes_by`` API with the "namespace" strategy.
That public dispatcher routes to the grouping implementation of interest,
which therefore runs three times over 25 nodes in total, through inner
dependency loops with same-key skips, duplicate-parent skips, empty parent
sets, nested namespaces, and bare (namespace-less) nodes on both the node
side and the parent side.

Everything is constructed from fixed loops and string formatting: no random
ness, no clock, no I/O beyond what kedro itself does in memory.
"""

import unittest

from kedro.pipeline import Pipeline, node


def _passthrough(*args):
    return args[0] if args else None


def _mk(namespace, name, inputs, output):
    return node(
        func=_passthrough,
        inputs=inputs,
        outputs=output,
        name=name,
        namespace=namespace,
    )


def _build_layered_mesh():
    """Four namespace tiers wired so that one group ends up with three
    parents that all collapse to a single dependency entry, plus an
    idle node and a nested-namespace node whose parent shares its key."""
    nodes = []
    tiers = ["ingest", "features", "train", "serve"]
    # tier 0: two source nodes
    for tag in ("a", "b"):
        nodes.append(_mk(tiers[0], "%s_%s" % (tiers[0], tag), None, "raw_" + tag))
    # tier 1: one single-parent node, one node with two same-tier parents
    nodes.append(_mk(tiers[1], tiers[1] + "_a", ["raw_a"], "feat_a_out"))
    nodes.append(
        _mk(tiers[1], tiers[1] + "_b", ["raw_a", "raw_b"], "feat_b_out")
    )
    # tier 2: nested namespaces; train_c fans in from both features nodes
    nodes.append(
        _mk(tiers[2] + ".primary", tiers[2] + "_a", ["feat_a_out"], "model_a")
    )
    nodes.append(
        _mk(tiers[2] + ".secondary", tiers[2] + "_b", ["feat_b_out"], "model_b")
    )
    nodes.append(
        _mk(
            tiers[2] + ".primary",
            tiers[2] + "_c",
            ["feat_a_out", "feat_b_out"],
            "model_c",
        )
    )
    # tier 3: three parents whose top-level key is identical
    nodes.append(
        _mk(
            tiers[3],
            tiers[3] + "_a",
            ["model_a", "model_b", "model_c"],
            "pred_a",
        )
    )
    # idle node: no parents at all
    nodes.append(_mk(tiers[3], tiers[3] + "_idle", None, "pred_idle"))
    # nested namespace sharing the tier key; its parent is in the same key
    nodes.append(_mk(tiers[3] + ".deep", tiers[3] + "_b", ["pred_a"], "pred_b"))
    return Pipeline(nodes)


def _build_mixed_bare():
    """Bare nodes (no namespace) interleaved with namespaced ones, in both
    dependency directions, so keys sometimes come from node names instead
    of namespaces — on the node side and on the parent side."""
    nodes = []
    nodes.append(_mk(None, "standalone_src", None, "s0"))
    nodes.append(_mk("mix", "mix_a", ["s0"], "m0"))
    nodes.append(_mk(None, "standalone_mid", ["m0"], "s1"))
    nodes.append(_mk("mix.inner", "mix_b", ["s1"], "m1"))
    nodes.append(_mk(None, "standalone_sink", ["m1"], "s2"))
    nodes.append(_mk(None, "standalone_free", None, "s3"))
    nodes.append(_mk("lone", "lone_a", None, "l0"))
    # two parents: one foreign-namespace, one sharing this node's own key
    nodes.append(_mk("mix", "mix_c", ["l0", "m0"], "m2"))
    return Pipeline(nodes)


def _build_dedup_diamond():
    """A diamond where every fan-in node has two parents whose top-level
    namespace keys coincide, forcing duplicate-suppression passes, and a
    deeply nested sink whose parent key equals its own key."""
    nodes = []
    for wing in ("alpha", "beta"):
        nodes.append(
            _mk("src." + wing, "src_" + wing[0], None, "d_" + wing[0])
        )
    nodes.append(_mk("mid.left", "left_a", ["d_a", "d_b"], "e_left"))
    nodes.append(_mk("mid.right", "right_a", ["d_a", "d_b"], "e_right"))
    nodes.append(_mk("snk", "snk_a", ["e_left", "e_right"], "f0"))
    nodes.append(_mk(None, "tail_a", ["f0"], "g0"))
    nodes.append(_mk("snk.lower.deeper", "snk_b", ["f0"], "g1"))
    return Pipeline(nodes)


class TestGroupByNamespaceDataFlow(unittest.TestCase):
    def test_traced_run(self):
        builders = [_build_layered_mesh, _build_mixed_bare, _build_dedup_diamond]
        pipelines = [build() for build in builders]

        all_grouped = []
        for pipe in pipelines:
            all_grouped.append(pipe.group_nodes_by(group_by="namespace"))

        # The dispatcher must have produced one grouping per pipeline.
        self.assertEqual(len(all_grouped), len(pipelines))

        total_nodes = 0
        for pipe, grouped in zip(pipelines, all_grouped):
            names = [g.name for g in grouped]
            # group names are unique within one grouping
            self.assertEqual(len(names), len(set(names)))
            # every pipeline node lands in exactly one group
            covered = [n for g in grouped for n in g.nodes]
            self.assertEqual(
                sorted(covered), sorted(nd.name for nd in pipe.nodes)
            )
            total_nodes += len(pipe.nodes)
            for g in grouped:
                self.assertIn(g.type, {"namespace", "nodes"})
                # no group depends on itself, and no duplicate entries
                self.assertEqual(
                    len(g.dependencies), len(set(g.dependencies))
                )
                for dep in g.dependencies:
                    self.assertIn(dep, names)
                    self.assertNotEqual(dep, g.name)

        # environment sanity: the scenario really is the size we designed
        self.assertEqual(total_nodes, sum(1 for _ in range(10)) + 8 + 7)
        # groups per pipeline, in build order (small structural counts)
        self.assertEqual([len(g) for g in all_grouped], [2 + 2, 2 * 3, 4])


if __name__ == "__main__":
    unittest.main()
