from __future__ import annotations

import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from instructlab.data import generate_data
from instructlab.defaults import ILAB_PROCESS_MODES
from instructlab.process import process as process_module


class FakeRegistry:
    def __init__(self):
        self.added = []
        self.persist_count = 0

    def load(self):
        return self

    def add(self, key, value):
        self.added.append((key, value))
        return self

    def persist(self):
        self.persist_count += 1
        return self


class TestAddProcessDataFlow(unittest.TestCase):
    def test_generated_mode_and_startup_matrix(self):
        registry = FakeRegistry()
        attached_payloads = []
        startup_calls = 0

        def foreground_entry(**values):
            attached_payloads.append(
                sum(
                    (position + 1) * len(str(value))
                    for position, value in enumerate(values.values())
                )
            )

        def simulated_start(**_values):
            nonlocal startup_calls
            startup_calls += 1
            if (startup_calls * startup_calls + 5 * startup_calls + 3) % 7 == 2:
                return None, None
            width = 2 + (startup_calls * 3) % 4
            return 4000 + startup_calls * 17, [
                5000 + startup_calls * 19 + offset for offset in range(width)
            ]

        parameter_names = tuple(inspect.signature(generate_data.gen_data).parameters)

        with tempfile.TemporaryDirectory() as temp_dir:
            log_root = Path(temp_dir) / "runtime-logs"
            with (
                mock.patch.object(
                    process_module, "ProcessRegistry", return_value=registry
                ),
                mock.patch.object(process_module, "start_process", side_effect=simulated_start),
                mock.patch.object(
                    process_module,
                    "format_command",
                    side_effect=lambda **values: "|".join(sorted(values)),
                ),
                mock.patch.object(process_module.DEFAULTS, "_data_dir", str(log_root)),
            ):
                for index in range(sum((value * 5 + 1) % 4 for value in range(11))):
                    derived = sum(
                        (position + 3) * ord(character)
                        for position, character in enumerate(f"case-{index * index + 9}")
                    )
                    arguments = {
                        name: f"{name}-{derived:x}-{position}"
                        for position, name in enumerate(parameter_names)
                    }
                    arguments["http_client_params"] = {
                        key: "" if (derived + offset) % 3 else f"value-{derived + offset:x}"
                        for offset, key in enumerate(
                            (
                                "tls_client_cert",
                                "tls_client_key",
                                "tls_client_passwd",
                                "tls_insecure",
                            )
                        )
                    }
                    arguments["quiet"] = derived % 2 == 0
                    arguments["process_mode"] = (
                        ILAB_PROCESS_MODES.ATTACHED
                        if (derived + index) % 5 in (0, 1)
                        else ILAB_PROCESS_MODES.DETACHED
                    )

                    replacement = None if index == len(parameter_names) // 3 else foreground_entry
                    with mock.patch.object(
                        generate_data, "create_server_and_generate", replacement
                    ):
                        generate_data.gen_data(**arguments)

        self.assertGreater(startup_calls, 1)
        self.assertGreater(len(registry.added), startup_calls // 2)
        self.assertTrue(attached_payloads)
        self.assertEqual(registry.persist_count, len(registry.added))
