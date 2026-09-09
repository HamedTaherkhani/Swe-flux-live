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
    tiers = ["data_ingest", "feat_engine", "model_train", "inference_serve"]
    # tier 0: two source nodes
    for tag in ("alpha", "beta"):
        nodes.append(_mk(tiers[0], "%s_%s" % (tiers[0], tag), None, "raw_" + tag))
    # tier 1: both nodes fan in from both tier-0 outputs
    nodes.append(
        _mk(tiers[1], tiers[1] + "_primary", ["raw_alpha", "raw_beta"], "feat_alpha_out")
    )
    nodes.append(
        _mk(tiers[1], tiers[1] + "_secondary", ["raw_alpha", "raw_beta"], "feat_beta_out")
    )
    # tier 2: nested namespaces; gamma fans in from both features nodes plus raw
    nodes.append(
        _mk(
            tiers[2] + ".primary",
            tiers[2] + "_alpha",
            ["feat_alpha_out", "feat_beta_out", "raw_alpha", "raw_beta"],
            "model_alpha",
        )
    )
    nodes.append(
        _mk(
            tiers[2] + ".secondary",
            tiers[2] + "_beta",
            ["feat_alpha_out", "feat_beta_out", "raw_alpha"],
            "model_beta",
        )
    )
    nodes.append(
        _mk(
            tiers[2] + ".primary",
            tiers[2] + "_gamma",
            ["feat_alpha_out", "feat_beta_out", "raw_alpha"],
            "model_gamma",
        )
    )
    # tier 3: seven parents spanning ingest, features, and train keys
    nodes.append(
        _mk(
            tiers[3],
            tiers[3] + "_main",
            [
                "model_alpha",
                "model_beta",
                "model_gamma",
                "feat_alpha_out",
                "feat_beta_out",
                "raw_alpha",
                "raw_beta",
            ],
            "pred_main",
        )
    )
    # idle node: no parents at all
    nodes.append(_mk(tiers[3], tiers[3] + "_idle", None, "pred_idle"))
    # nested namespace sharing the tier key; parents mix same-key and foreign-key
    nodes.append(
        _mk(
            tiers[3] + ".deep.nested",
            tiers[3] + "_nested",
            ["pred_main", "feat_alpha_out", "feat_beta_out", "raw_alpha"],
            "pred_nested",
        )
    )
    return Pipeline(nodes)


def _build_mixed_bare():
    """Bare nodes (no namespace) interleaved with namespaced ones, in both
    dependency directions, so keys sometimes come from node names instead
    of namespaces — on the node side and on the parent side."""
    nodes = []
    nodes.append(_mk(None, "bare_source_alpha", None, "bs_alpha"))
    nodes.append(_mk("mix.outer", "mix_alpha", ["bs_alpha"], "mix_out_alpha"))
    nodes.append(_mk(None, "bare_bridge_beta", ["mix_out_alpha", "bs_alpha"], "bs_beta"))
    nodes.append(_mk("mix.inner.deep", "mix_beta", ["bs_beta", "bs_alpha"], "mix_out_beta"))
    nodes.append(_mk(None, "bare_sink_gamma", ["mix_out_beta", "mix_out_alpha"], "bs_gamma"))
    nodes.append(_mk(None, "bare_isolated_delta", None, "bs_delta"))
    nodes.append(_mk("lone.tower", "lone_alpha", None, "lone_out"))
    # five parents: foreign bare keys, same-key mix parents, and lone
    nodes.append(
        _mk(
            "mix.outer",
            "mix_gamma",
            ["lone_out", "mix_out_alpha", "bs_beta", "mix_out_beta", "bs_alpha"],
            "mix_out_gamma",
        )
    )
    return Pipeline(nodes)


def _build_dedup_diamond():
    """A diamond where every fan-in node has two parents whose top-level
    namespace keys coincide, forcing duplicate-suppression passes, and a
    deeply nested sink whose parent key equals its own key."""
    nodes = []
    for wing in ("north", "south"):
        nodes.append(
            _mk("src." + wing + ".wing", "src_" + wing[0], None, "d_" + wing[0])
        )
    nodes.append(_mk("mid.left.branch", "left_alpha", ["d_n", "d_s"], "e_left_alpha"))
    nodes.append(_mk("mid.right.branch", "right_beta", ["d_n", "d_s"], "e_right_beta"))
    nodes.append(
        _mk(
            "snk.hub",
            "snk_alpha",
            ["e_left_alpha", "e_right_beta", "d_n", "d_s"],
            "f_hub",
        )
    )
    nodes.append(
        _mk(
            None,
            "tail_terminal",
            ["f_hub", "e_left_alpha", "e_right_beta", "d_n", "d_s"],
            "g_terminal",
        )
    )
    nodes.append(
        _mk(
            "snk.lower.deeper.core",
            "snk_beta",
            ["f_hub", "e_left_alpha", "e_right_beta"],
            "g_deep",
        )
    )
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
