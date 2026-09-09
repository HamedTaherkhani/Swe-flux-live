import builtins
import importlib
import pathlib
import random
import types
import unittest
from unittest import mock

from instructlab.model.backends import backends, llama_cpp


class TestServeBackendExceptionPaths(unittest.TestCase):
    def test_cli_serve_handles_backend_failures_before_shutdown(self):
        cli_module = importlib.import_module("instructlab.cli.model." + "serve")
        target_module = importlib.import_module(
            getattr(cli_module, "serve_" + "backend").__module__
        )
        backend_error = getattr(
            importlib.import_module("instructlab.model.backends." + "common"),
            "Server" + "Exception",
        )
        interrupt_error = getattr(builtins, "Keyboard" + "Interrupt")

        rng = random.Random(sum(index * index for index in range(19)))
        schedule = [
            (backend_error if rng.randrange(7) % 3 else interrupt_error)
            for _ in range(17)
        ]
        schedule[sum(range(4)) % len(schedule)] = backend_error
        schedule[sum(range(5)) % len(schedule)] = interrupt_error

        activity = []

        class FakeServer:
            created = 0

            def __init__(self, **kwargs):
                self.index = type(self).created
                type(self).created += 1
                activity.append(("created", self.index, len(kwargs)))

            def run(self):
                exc_type = schedule[self.index]
                checksum = sum(
                    (position + 1) * ord(character)
                    for position, character in enumerate(exc_type.__name__)
                )
                raise exc_type(f"backend-cycle-{self.index}-{checksum % 997}")

            def shutdown(self):
                activity.append(("shutdown", self.index))

        config = types.SimpleNamespace(
            serve=types.SimpleNamespace(
                server=types.SimpleNamespace(
                    backend_type=None,
                    current_max_ctx_size=None,
                ),
                chat_template=None,
                api_base=lambda: "http://127.0.0.1:9999",
            )
        )

        class FakeContext:
            def __init__(self):
                self.args = []
                self.obj = types.SimpleNamespace(config=config)

            @staticmethod
            def get_parameter_source(_name):
                return None

        entrypoint = cli_module.serve.callback
        while hasattr(entrypoint, "__wrapped__"):
            entrypoint = entrypoint.__wrapped__

        exits = []
        with (
            mock.patch.object(backends, "get", return_value=backends.LLAMA_CPP),
            mock.patch.object(llama_cpp, "Server", FakeServer),
            mock.patch.object(cli_module, "write_config"),
            mock.patch.object(target_module, "write_config"),
        ):
            for index in range(len(schedule)):
                try:
                    entrypoint(
                        ctx=FakeContext(),
                        model_path=pathlib.Path(f"/models/generated-{index}"),
                        gpu_layers=sum(range(index % 9)),
                        num_threads=None,
                        max_ctx_size=sum(range(33)) + index,
                        model_family=f"family-{index % 5}",
                        log_file=None,
                        backend=backends.LLAMA_CPP,
                        chat_template=None,
                        gpus=None,
                        host="127.0.0.1",
                        port=8000 + index,
                    )
                except BaseException as exc:
                    exits.append(getattr(exc, "code", None))

        self.assertEqual(len(exits), len(schedule))
        self.assertTrue(all(code == sum(()) for code in exits))
        self.assertEqual(
            sum(kind == "shutdown" for kind, *_ in activity),
            len(schedule),
        )
