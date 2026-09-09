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

        rng = random.Random(sum(index * index * index for index in range(27)))
        schedule = [
            (backend_error if rng.randrange(13) % 5 else interrupt_error)
            for _ in range(47)
        ]
        schedule[sum(range(6)) % len(schedule)] = backend_error
        schedule[sum(range(7)) % len(schedule)] = interrupt_error
        schedule[sum(range(8)) % len(schedule)] = backend_error
        schedule[sum(range(9)) % len(schedule)] = interrupt_error
        schedule[sum(range(10)) % len(schedule)] = backend_error
        schedule[sum(range(11)) % len(schedule)] = interrupt_error

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
                raise exc_type(f"backend-cycle-{self.index}-{checksum % 1009}")

            def shutdown(self):
                activity.append(("shutdown", self.index))

        config = types.SimpleNamespace(
            serve=types.SimpleNamespace(
                server=types.SimpleNamespace(
                    backend_type=None,
                    current_max_ctx_size=None,
                ),
                chat_template="default-template-alpha",
                api_base=lambda: "http://127.0.0.1:8888",
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
                        model_path=pathlib.Path(
                            f"/models/generated-{index % 17}-{index}"
                        ),
                        gpu_layers=(index * 7 + 5) % 23,
                        num_threads=index % 6 if index % 4 else None,
                        max_ctx_size=(
                            4096
                            if index % 11 == 0
                            else 4096 + (index % 21) * 96 - (index % 7) * 48
                        ),
                        model_family=f"family-{index % 9}-variant",
                        log_file=(
                            pathlib.Path(f"/tmp/serve-backend-{index % 11}.log")
                            if index % 3
                            else None
                        ),
                        backend=backends.LLAMA_CPP,
                        chat_template=(
                            f"template-{index % 8}-beta"
                            if index % 2
                            else None
                        ),
                        gpus=None,
                        host="127.0.0.1" if index % 6 else "0.0.0.0",
                        port=8200 + index * 5,
                    )
                except BaseException as exc:
                    exits.append(getattr(exc, "code", None))

        self.assertEqual(len(exits), len(schedule))
        self.assertTrue(all(code == sum(()) for code in exits))
        self.assertEqual(
            sum(kind == "shutdown" for kind, *_ in activity),
            len(schedule),
        )
