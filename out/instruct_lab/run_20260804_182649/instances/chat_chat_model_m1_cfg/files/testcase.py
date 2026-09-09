import importlib
import types
import unittest
from pathlib import Path
from unittest import mock

import requests


class TestChatCommandPaths(unittest.TestCase):
    def test_cli_dispatches_varied_server_routes(self):
        cli_module = importlib.import_module("instructlab.cli.model.chat")
        runtime = importlib.import_module("instructlab.model.chat")
        backend_common = importlib.import_module(
            "instructlab.model.backends.common"
        )

        entry = cli_module.chat.callback
        while hasattr(entry, "__wrapped__"):
            entry = entry.__wrapped__

        activity = []

        class FakeBackend:
            serial = 0

            def __init__(self, should_fail):
                type(self).serial += 1
                self.serial = type(self).serial
                self.should_fail = should_fail

            def get_backend_type(self):
                activity.append(("kind", self.serial))
                return f"backend-{self.serial}"

            def run_detached(self, client):
                activity.append(("run", self.serial, client is not None))
                if self.should_fail:
                    raise requests.RequestException(
                        "-".join(chr(97 + ((self.serial + i) % 20)) for i in range(9))
                    )
                return "/".join(("http:", "", "generated", str(self.serial)))

            def shutdown(self):
                activity.append(("shutdown", self.serial))

        generated_backends = iter((FakeBackend(False), FakeBackend(True)))

        config = types.SimpleNamespace(
            serve=types.SimpleNamespace(
                server=types.SimpleNamespace(
                    backend_type="initial",
                    host=".".join(str((i * 17) % 251) for i in range(4)),
                    port=sum(i * i for i in range(8)),
                    current_max_ctx_size=sum(range(33)),
                ),
                backend="generated-backend",
                chat_template=None,
                api_base=lambda: "/".join(("http:", "", "configured", "v1")),
                llama_cpp=types.SimpleNamespace(
                    gpu_layers=-1,
                    max_ctx_size=sum(i for i in range(25) if i % 3),
                ),
                vllm=types.SimpleNamespace(
                    llm_family="generated-family",
                    vllm_args=[f"--option-{i}" for i in range(18)],
                    max_startup_attempts=sum(
                        1 for i in range(30) if i % 4 == 0
                    ),
                ),
            ),
            chat=types.SimpleNamespace(
                logs_dir=Path("/tmp") / "generated-chat-logs",
                vi_mode=False,
                visible_overflow=True,
            ),
        )
        ctx = types.SimpleNamespace(
            obj=types.SimpleNamespace(config=config),
            params={"api_key": "".join(chr(107 + (i % 5)) for i in range(24))},
        )

        base = {
            "ctx": ctx,
            "question": tuple(f"part-{i * i % 23}" for i in range(20)),
            "model": "/".join(("", "models", "generated-model")),
            "context": "default",
            "session": None,
            "quick_question": True,
            "max_tokens": sum(range(16)),
            "endpoint_url": None,
            "api_key": ctx.params["api_key"],
            "tls_insecure": False,
            "tls_client_cert": "",
            "tls_client_key": "",
            "tls_client_passwd": "",
            "model_family": None,
            "serving_log_file": None,
            "temperature": sum(i % 3 for i in range(21)) / 20,
            "rag_enabled": False,
            "uri": "memory://generated",
            "collection_name": "generated-collection",
            "embedding_model_path": "/generated/embedding",
            "top_k": sum(1 for i in range(22) if i % 3 == 1),
            "no_decoration": False,
        }

        def invoke(**changes):
            arguments = dict(base)
            arguments.update(changes)
            return entry(**arguments)

        server_models = types.SimpleNamespace(
            data=[
                types.SimpleNamespace(id=f"served-{(i * 11) % 29}")
                for i in range(17)
            ]
        )

        with (
            mock.patch.object(runtime.FeatureGating, "feature_available", return_value=False),
            mock.patch.object(
                runtime,
                "is_openai_server_and_serving_model",
                side_effect=(True, False, False),
            ),
            mock.patch.object(
                backend_common,
                "is_temp_server_running",
                side_effect=(True, False, True),
            ),
            mock.patch.object(
                runtime.backends,
                "get_backend_from_values",
                side_effect=lambda **_kwargs: next(generated_backends),
            ),
            mock.patch.object(runtime, "http_client", return_value=object()),
            mock.patch.object(runtime.ilabclient, "list_models", return_value=server_models),
            mock.patch.object(runtime.log, "add_file_handler_to_logger"),
            mock.patch.object(
                runtime,
                "chat_cli",
                side_effect=(None, None, runtime.ChatException("generated failure")),
            ),
        ):
            invoke(rag_enabled=True)
            invoke(endpoint_url="/".join(("https:", "", "remote", "v1")))
            invoke(
                model=runtime.cfg.DEFAULTS.GRANITE_GGUF_MODEL_NAME,
                serving_log_file=Path("/tmp") / "generated-serving.log",
            )
            with self.assertRaises(SystemExit):
                invoke(model="/".join(("", "models", "detached-success")))
            with self.assertRaises(SystemExit):
                invoke(
                    model="/".join(("", "models", "detached-failure")),
                    serving_log_file=Path("/tmp") / "generated-failure.log",
                )

        self.assertGreater(len(activity), len(config.serve.vllm.vllm_args) // 4)
        self.assertTrue(any(item[0] == "shutdown" for item in activity))
        self.assertNotEqual(activity[0][0], activity[-1][0])
