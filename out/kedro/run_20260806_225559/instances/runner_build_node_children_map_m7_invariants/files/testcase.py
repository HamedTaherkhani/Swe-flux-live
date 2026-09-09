"""Deterministic exercise of kedro's missing-outputs runner path.

The test programmatically builds several layered ``Pipeline`` objects.  Each
scenario varies the layer count, the layer width, the fan-in between layers,
how many first-layer nodes take a second external input, and whether the
first layer is made of source nodes (no inputs at all).  For every scenario
the test calls ``SequentialRunner.run(..., only_missing_outputs=True)``
exactly once, which walks the call chain ``AbstractRunner.run`` ->
``AbstractRunner._filter_pipeline_for_missing_outputs`` down to the
children-map construction logic two frames below ``run``.  Each scenario
therefore produces exactly one invocation of that logic with a different
(node, input-dataset) footprint.
"""

import unittest

from kedro.io import DataCatalog, MemoryDataset
from kedro.pipeline import Pipeline, node
from kedro.runner import SequentialRunner


def _combine(*args):
    return len(args)


# (layers, width, fanin, extra_mod, source_layer0)
SCENARIOS = [
    (4, 5, 2, 3, 0),
    (5, 4, 2, 0, 0),
    (3, 6, 3, 4, 0),
    (5, 5, 1, 2, 0),
    (4, 4, 2, 0, 1),
]


def build_pipeline(layers, width, fanin, extra_mod, source_layer0):
    nodes = []
    ext_names = set()
    for i in range(layers):
        for j in range(width):
            if i == 0:
                if source_layer0:
                    inputs = None
                else:
                    inputs = [f"ext{j}"]
                    if extra_mod and j % extra_mod == 0:
                        inputs.append(f"ext_shared_{j % 3}")
                    ext_names.update(inputs or [])
            else:
                inputs = [f"m{i-1}_{(j + k) % width}" for k in range(fanin)]
            nodes.append(
                node(
                    func=_combine,
                    inputs=inputs,
                    outputs=f"m{i}_{j}",
                    name=f"n{i}_{j}",
                )
            )
    return Pipeline(nodes), sorted(ext_names)


def build_catalog(pipeline, ext_names):
    datasets = {}
    for name in ext_names:
        datasets[name] = MemoryDataset(data=[name])
    for nd in pipeline.nodes:
        for out in nd.outputs:
            datasets[out] = MemoryDataset()
    return DataCatalog(datasets)


class TestChildrenMapInvariants(unittest.TestCase):
    def test_traced_run(self):
        runner = SequentialRunner()
        self.assertGreaterEqual(len(SCENARIOS), 3)
        for spec in SCENARIOS:
            pipeline, ext_names = build_pipeline(*spec)
            catalog = build_catalog(pipeline, ext_names)
            result = runner.run(pipeline, catalog, only_missing_outputs=True)
            self.assertIsInstance(result, dict)
            self.assertTrue(set(result).issubset(set(pipeline.outputs())))


if __name__ == "__main__":
    unittest.main()
