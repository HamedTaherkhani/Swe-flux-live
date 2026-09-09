from __future__ import annotations

import random
import unittest

from kedro.io import DataCatalog, MemoryDataset
from kedro.pipeline import node, pipeline
from kedro.runner import SequentialRunner


def _generate_measurements(seed_value: int, *, width: int) -> list[int]:
    generator = random.Random(seed_value)
    state = seed_value
    measurements = []
    for position in range(width):
        state = (
            state * (position % 9 + 3)
            + generator.getrandbits(position % 13 + 7)
            + position * position
        ) % 1_000_003
        measurements.append(state ^ generator.getrandbits(12))
    return measurements


class TestAsyncNodeOutputInvariants(unittest.TestCase):
    def test_seeded_multi_output_pipeline(self) -> None:
        seed_value = sum(
            (index + 3) * ord(character)
            for index, character in enumerate("threaded-catalog")
        )
        output_count = sum((ord(character) % 5) + 2 for character in "executor")
        output_names = [
            f"measurement_{index:02d}_{(index * index + seed_value) % 97:02d}"
            for index in range(output_count)
        ]
        generated_node = node(
            _generate_measurements,
            inputs={"seed_value": "seed", "width": "params:width"},
            outputs=output_names,
            name="generate_seeded_measurements",
        )
        catalog = DataCatalog(
            {
                "seed": MemoryDataset(seed_value),
                "params:width": MemoryDataset(output_count),
                **{name: MemoryDataset() for name in output_names},
            }
        )

        result = SequentialRunner(is_async=True).run(
            pipeline([generated_node]), catalog
        )

        self.assertEqual(set(result), set(output_names))
        self.assertTrue(all(isinstance(dataset.load(), int) for dataset in result.values()))
