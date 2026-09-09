from __future__ import annotations

import unittest
from functools import partial

from kedro.io import DataCatalog, MemoryDataset
from kedro.pipeline import node, pipeline
from kedro.runner import ThreadRunner


def _varying_transform(value: int, *, factor: int, bias: int) -> int:
    return (value * factor + bias) % 1_000_003


class TestThreadedDependencyScheduling(unittest.TestCase):
    def test_programmatic_dependency_chain(self) -> None:
        node_count = sum((ord(character) % 7) + 1 for character in "dependency")
        generated_nodes = []

        for index in range(node_count):
            input_name = "seed" if index == 0 else f"stage_{index - 1}"
            output_name = f"stage_{index}"
            generated_nodes.append(
                node(
                    partial(
                        _varying_transform,
                        factor=(index * index) % 11 + 2,
                        bias=index * 17 + 3,
                    ),
                    inputs=input_name,
                    outputs=output_name,
                    name=f"transform_{index}",
                )
            )

        initial_value = sum(
            (position + 1) * ord(character)
            for position, character in enumerate("seeded")
        )
        catalog = DataCatalog({"seed": MemoryDataset(initial_value)})
        result = ThreadRunner(max_workers=1).run(pipeline(generated_nodes), catalog)

        final_dataset = result[f"stage_{node_count - 1}"]
        final_value = final_dataset.load()
        self.assertEqual(set(result), {f"stage_{node_count - 1}"})
        self.assertIsInstance(final_value, int)
        self.assertGreaterEqual(final_value, 0)
        self.assertLess(final_value, 1_000_003)
