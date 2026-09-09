from __future__ import annotations

import importlib
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestIPythonPrepareImportsDataFlow(unittest.TestCase):
    def test_generated_magic_sources(self) -> None:
        ipython_module = importlib.import_module("kedro.ipython")

        def build_source(seed: int, width: int) -> str:
            rng = random.Random(seed)
            lines: list[str] = []
            inside_group = False
            group_depth = 0
            for index in range(width):
                token = rng.randrange(100_000, 1_000_000)
                if inside_group:
                    group_depth += 1
                    if group_depth >= 5 or rng.randrange(5) == 0:
                        lines.append(")")
                        inside_group = False
                    else:
                        lines.append(f"symbol_{index}_{token},")
                    continue

                selector = (rng.randrange(17) + index * seed) % 9
                if selector in (0, 1):
                    lines.append(f"import package_{token}")
                elif selector == 2:
                    lines.append(f"from package_{token} import symbol_{index}")
                elif selector == 3:
                    lines.append(f"from package_{token} import (")
                    inside_group = True
                    group_depth = 0
                else:
                    lines.append(f"payload_{index} = {token} ** 2")

            if inside_group:
                lines.append(")")
            return "\n".join(lines) + "\n"

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            seeds = [9103 + index * 2081 for index in range(4)]
            source_paths = []
            for index, seed in enumerate(seeds):
                source_path = root / f"generated_{index}_{seed}.py"
                source_path.write_text(
                    build_source(seed, 67 + index * 3), encoding="utf-8"
                )
                source_paths.append(source_path)

            node_functions = [
                (lambda marker=index: marker) for index in range(len(source_paths))
            ]
            nodes = [
                SimpleNamespace(func=node_function)
                for node_function in node_functions
            ]
            node_by_name = {
                f"generated_node_{index}": generated_node
                for index, generated_node in enumerate(nodes)
            }

            with (
                patch.object(
                    ipython_module.inspect,
                    "getsourcefile",
                    side_effect=[str(path) for path in source_paths],
                ) as source_lookup,
                patch.object(
                    ipython_module,
                    "_find_node",
                    side_effect=lambda name, registered: node_by_name[name],
                ),
                patch.object(
                    ipython_module,
                    "_prepare_function_body",
                    return_value="def generated():\n    pass",
                ),
                patch.object(
                    ipython_module,
                    "_get_node_bound_arguments",
                    return_value=SimpleNamespace(),
                ),
                patch.object(
                    ipython_module, "_prepare_node_inputs", return_value=None
                ),
                patch.object(
                    ipython_module, "_format_node_inputs_text", return_value=None
                ),
                patch.object(
                    ipython_module,
                    "_prepare_function_call",
                    return_value="generated()",
                ),
                patch.object(
                    ipython_module, "_guess_run_environment", return_value="ipython"
                ),
                patch.object(ipython_module, "_create_cell_with_text") as create_cell,
            ):
                for node_name in node_by_name:
                    ipython_module.magic_load_node(node_name)

            self.assertEqual(source_lookup.call_count, len(source_paths))
            self.assertEqual(create_cell.call_count, len(node_by_name))
            self.assertTrue(
                all(path.stat().st_size > len(source_paths) for path in source_paths)
            )
