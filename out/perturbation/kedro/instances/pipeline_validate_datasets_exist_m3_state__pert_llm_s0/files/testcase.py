import random
import unittest

from kedro.pipeline import node, pipeline
from kedro.pipeline.pipeline import PipelineError


class TestValidateDatasetsExistState(unittest.TestCase):
    def test_seeded_invalid_dataset_mappings(self):
        rng = random.Random(0xB17C0DE)

        dataset_names = [
            f"telemetry_{index:02x}_{rng.randrange(1 << 20):05x}_raw"
            for index in range(120)
        ]

        def identity(value):
            return value

        nodes = [
            node(
                identity,
                dataset_names[index],
                f"{dataset_names[index]}_processed",
                name=f"transform_{index:02x}",
            )
            for index in range(len(dataset_names))
        ]

        chosen = rng.sample(range(len(dataset_names)), len(dataset_names) * 11 // 12)
        mappings = {}
        for rank, index in enumerate(chosen):
            original = dataset_names[index]
            position = 2 + (index * 7 + rank * 11) % (len(original) - 6)
            misspelled = original[:position] + original[position + 1 :]
            mappings[misspelled] = f"external_{rank:02x}"

        with self.assertRaises(PipelineError) as caught:
            pipeline(nodes, inputs=mappings, namespace="validation_scope")

        message = str(caught.exception)
        self.assertGreater(len(message), sum(map(len, mappings)) // 2)
        self.assertTrue(all(name in message for name in mappings))
