"""Deterministic exercise of kedro's resumed-pipeline suggestion path.

The test programmatically builds several layered ``Pipeline`` objects.  Each
scenario varies the layer count, the layer width, the fan-in between layers,
which intermediate datasets are registered as persisted in the catalog, and
which nodes are reported as already done.  For every scenario the test calls
``AbstractRunner._suggest_resume_scenario`` on a ``SequentialRunner``
instance exactly once, which walks the resume-suggestion call chain down to
the node-discovery logic two frames below it.  Each scenario therefore
produces one invocation of that logic with a different breadth-first-search
footprint.
"""

import unittest

from kedro.io import AbstractDataset, DataCatalog
from kedro.pipeline import Pipeline, node
from kedro.runner import SequentialRunner


class PersistentDataset(AbstractDataset):
    """Minimal non-ephemeral dataset: ``_EPHEMERAL`` stays False."""

    def _load(self):
        return None

    def _save(self, data):
        pass

    def _describe(self):
        return {}

    def _exists(self):
        return True


def _combine(*args):
    return None


# (layers, width, fanin, persist_mod, persist_off, done_mod, done_rem)
SCENARIOS = [
    (4, 5, 2, 3, 0, 5, 1),
    (5, 4, 2, 4, 1, 4, 1),
    (3, 6, 3, 2, 0, 3, 1),
    (5, 5, 1, 5, 2, 6, 2),
    (4, 6, 2, 3, 1, 2, 1),
    (6, 3, 2, 4, 3, 5, 2),
]


def build_scenario(layers, width, fanin, persist_mod, persist_off, done_mod, done_rem):
    nodes = []
    indexed = {}
    for i in range(layers):
        for j in range(width):
            if i == 0:
                inputs = [f"ext{j}"]
            else:
                inputs = [f"m{i-1}_{(j + 1 + k) % width}" for k in range(fanin)]
            nd = node(
                func=_combine, inputs=inputs, outputs=f"m{i}_{j}", name=f"n{i}_{j}"
            )
            nodes.append(nd)
            indexed[(i, j)] = nd
    pipeline = Pipeline(nodes)

    datasets = {}
    for i in range(layers):
        for j in range(width):
            if (i * width + j + persist_off) % persist_mod == 0:
                datasets[f"m{i}_{j}"] = PersistentDataset()
    catalog = DataCatalog(datasets)

    done_nodes = [
        indexed[(i, j)]
        for i in range(layers)
        for j in range(width)
        if (i * width + j) % done_mod < done_rem
    ]
    return pipeline, catalog, done_nodes


class TestResumePipelineLoops(unittest.TestCase):
    def test_traced_run(self):
        runner = SequentialRunner()
        for spec in SCENARIOS:
            pipeline, catalog, done_nodes = build_scenario(*spec)
            self.assertTrue(done_nodes)
            self.assertLess(len(done_nodes), len(pipeline.nodes))
            with self.assertLogs("kedro.runner", level="WARNING") as caught:
                runner._suggest_resume_scenario(pipeline, done_nodes, catalog)
            text = "\n".join(caught.output)
            self.assertIn("--from-nodes", text)


if __name__ == "__main__":
    unittest.main()
