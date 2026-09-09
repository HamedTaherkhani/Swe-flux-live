from __future__ import annotations

import importlib
import random
import unittest
import warnings
from unittest.mock import patch

from kedro.pipeline import node, pipeline


def generated_debug_node(primary, *extras):
    return (primary, extras)


class _RecordingShell:
    def __init__(self) -> None:
        self.cells: list[str] = []

    def set_next_input(self, text: str) -> None:
        self.cells.append(text)


class TestIPythonLoadNodeCallGraph(unittest.TestCase):
    def test_generated_node_magic_calls(self) -> None:
        ipython_module = importlib.import_module("kedro.ipython")
        rng = random.Random(731_927)
        node_count = 24
        generated_nodes = []

        for index in range(node_count):
            input_count = 2 + ((rng.randrange(97) + index * 11) % 7)
            inputs = [
                f"dataset_{index}_{position}_{rng.randrange(10_000, 99_999)}"
                for position in range(input_count)
            ]
            generated_nodes.append(
                node(
                    generated_debug_node,
                    inputs=inputs,
                    outputs=f"result_{index}_{rng.randrange(100_000, 999_999)}",
                    name=f"debug_node_{index}_{rng.randrange(100_000, 999_999)}",
                )
            )

        buckets = [[] for _ in range(6)]
        for index, generated_node in enumerate(generated_nodes):
            bucket = (index * 5 + rng.randrange(6)) % len(buckets)
            buckets[bucket].append(generated_node)
        generated_pipelines = [pipeline(bucket) for bucket in buckets]

        call_order = list(range(node_count))
        rng.shuffle(call_order)
        shell = _RecordingShell()

        with (
            patch.object(
                ipython_module.pipelines,
                "values",
                return_value=generated_pipelines,
            ),
            patch.object(ipython_module, "get_ipython", return_value=shell),
            patch.object(ipython_module, "_is_databricks", return_value=False),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore")
            for index in call_order:
                ipython_module.magic_load_node(generated_nodes[index].name)

        self.assertEqual(len(shell.cells), node_count)
        self.assertTrue(all("catalog.load" in cell for cell in shell.cells))
        self.assertGreater(sum(map(len, shell.cells)), node_count * node_count)
