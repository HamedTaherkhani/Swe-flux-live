import random
import unittest
import warnings

from kedro.pipeline import Pipeline, node


def _combine(*values):
    return sum(values)


class TestPipelineValidateNamespacesLoops(unittest.TestCase):
    def test_accumulated_namespace_state(self):
        seed = sum((index + 1) * ord(char) for index, char in enumerate("kedro-namespace"))
        rng = random.Random(seed)
        node_count = len("namespace-validation") * 3 + seed % 7

        nodes = []
        for index in range(node_count):
            if index == 0:
                inputs = ["external_input"]
            else:
                parent_limit = min(index, 6)
                parent_count = 1 + rng.randrange(parent_limit)
                parent_indexes = sorted(rng.sample(range(index), parent_count))
                inputs = [f"dataset_{parent}" for parent in parent_indexes]
            nodes.append(
                node(
                    _combine,
                    inputs,
                    f"dataset_{index}",
                    name=f"step_{index}",
                )
            )

        pipeline = Pipeline(nodes)
        roots = ("alpha", "beta", "gamma", "delta")
        rolling = seed
        for index, pipeline_node in enumerate(nodes):
            rolling = (rolling * 37 + rng.randrange(97) + index) % 1009
            selector = (rolling + index * index) % 11
            if selector in {0, 7}:
                namespace = None
            else:
                root = roots[(rolling + index) % len(roots)]
                depth = 1 + ((rolling // 7 + index) % 3)
                parts = [root]
                parts.extend(
                    f"level{(rolling // (offset + 2) + index + offset) % 5}"
                    for offset in range(depth - 1)
                )
                namespace = ".".join(parts)
            pipeline_node._namespace = namespace
            pipeline_node.__dict__.pop("namespace_prefixes", None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = pipeline._validate_namespaces()

        self.assertIsNone(result)
        self.assertEqual(len(pipeline.nodes), len(nodes))
        self.assertTrue(any(item.category is UserWarning for item in caught))
