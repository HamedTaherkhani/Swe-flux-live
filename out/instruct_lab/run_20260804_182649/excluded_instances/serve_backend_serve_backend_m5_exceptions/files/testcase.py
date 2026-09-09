import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from click.testing import CliRunner

from instructlab.configuration import get_default_config


class ServeBackendExceptionFlowTest(unittest.TestCase):
    def test_cli_drives_layered_backend_outcomes(self):
        command_module = importlib.import_module("instructlab.cli.model.serve")
        backend_module = importlib.import_module("instructlab.model.backends.llama_cpp")

        callback = command_module.serve.callback
        while hasattr(callback, "__wrapped__"):
            callback = callback.__wrapped__
        target = callback.__globals__["".join(("serve", "_", "backend"))]
        target_globals = target.__globals__

        plans = [(index * index + 3 * index + 7) % 5 for index in range(19)]
        created = []

        class ExercisingServer:
            def __init__(self, **_kwargs):
                self.token = len(created)
                created.append(self)

            def run(self):
                mode = plans[self.token]
                if mode == 0:
                    return sum(value ^ self.token for value in range(23))
                if mode == 1:
                    return [][self.token]
                if mode == 2:
                    return {}[str(self.token * 17 + 3)]
                if mode == 3:
                    return int(chr(97 + self.token % 19))
                return next(iter(()))

            def shutdown(self):
                return sum((self.token + value) % 7 for value in range(17))

        config = get_default_config()
        runner = CliRunner()
        results = []

        with (
            mock.patch.object(target_globals["backends"], "get", return_value="llama-cpp"),
            mock.patch.object(backend_module, "Server", ExercisingServer),
            mock.patch.dict(target_globals, {"write_config": lambda _config: None}),
            mock.patch.object(command_module, "write_config", lambda _config: None),
        ):
            for index in range(len(plans)):
                args = [
                    "--model-path",
                    str(Path("generated") / f"model-{index:02d}.gguf"),
                    "--gpu-layers",
                    str((index * 11) % 37),
                    "--max-ctx-size",
                    str(2048 + index * 64),
                    "--backend",
                    "llama-cpp",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(8100 + index),
                ]
                if (index * 7 + 2) % 6 == 0:
                    args.extend(["--", f"--generated-{index}", str(index**3 + 1)])
                results.append(
                    runner.invoke(
                        command_module.serve,
                        args,
                        obj=SimpleNamespace(config=config),
                    )
                )

        self.assertEqual(len(results), len(plans))
        self.assertEqual({result.exit_code == 0 for result in results}, {False, True})
        self.assertGreater(len(created), len(results) // 2)
        self.assertTrue(all(server.token == index for index, server in enumerate(created)))
