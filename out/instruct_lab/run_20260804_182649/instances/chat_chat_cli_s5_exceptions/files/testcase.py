import builtins
import unittest
from types import SimpleNamespace
from unittest import mock

from instructlab.model import chat as chat_module
from instructlab.model.backends import common as backend_common


class ChatModelExceptionFlowTest(unittest.TestCase):
    def test_generated_prompt_failures_are_handled(self):
        exception_types = [
            value
            for value in vars(builtins).values()
            if isinstance(value, type) and issubclass(value, BaseException)
        ]
        retry_type = next(
            value
            for value in exception_types
            if value.__name__.endswith("Interrupt") and value.__module__ == "builtins"
        )
        stop_type = next(
            value
            for value in exception_types
            if value.__name__.startswith("EOF") and value.__module__ == "builtins"
        )
        retry_count = sum(index % 3 for index in range(19))
        prompt_effects = [retry_type() for _ in range(retry_count)] + [stop_type()]

        model_records = [
            SimpleNamespace(id=f"served-{index:02d}-{(index * 17) % 29:02d}")
            for index in range(24)
        ]

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.models = SimpleNamespace(
                    list=lambda: SimpleNamespace(data=model_records)
                )

        class FakeConsoleChatBot:
            instances = []

            def __init__(self, *_args, **_kwargs):
                self.calls = 0
                self.effects = iter(prompt_effects)
                self.__class__.instances.append(self)

            def greet(self, **_kwargs):
                return None

            def start_prompt(self, *_args, **_kwargs):
                self.calls += 1
                raise next(self.effects)

        call_args = {
            "question": [],
            "model": "requested-model",
            "context": "generated-context",
            "session": None,
            "quick_question": False,
            "max_tokens": 128,
            "endpoint_url": "http://deterministic.invalid/v1",
            "api_key": "local-test-key",
            "tls_insecure": False,
            "tls_client_cert": None,
            "tls_client_key": None,
            "tls_client_passwd": None,
            "model_family": None,
            "serving_log_file": None,
            "temperature": 0.25,
            "rag_enabled": False,
            "document_store_uri": None,
            "collection_name": None,
            "embedding_model_path": None,
            "top_k": 3,
            "no_decoration": True,
            "backend_type": "generated",
            "host": "127.0.0.1",
            "port": 8000,
            "current_max_ctx_size": 4096,
            "params": {"api_key": "local-test-key"},
            "backend_name": "generated",
            "chat_template": None,
            "api_base": None,
            "gpu_layers": None,
            "max_ctx_size": 4096,
            "vllm_model_family": None,
            "vllm_args": None,
            "max_startup_attempts": 1,
            "logs_dir": None,
            "vi_mode": False,
            "visible_overflow": True,
        }

        with (
            mock.patch.object(chat_module, "OpenAI", FakeOpenAI),
            mock.patch.object(chat_module, "ConsoleChatBot", FakeConsoleChatBot),
            mock.patch.object(chat_module, "get_model_arch", return_value="generated"),
            mock.patch.object(chat_module, "http_client", return_value=None),
            mock.patch.object(backend_common, "is_temp_server_running", return_value=True),
        ):
            result = chat_module.chat_model(**call_args)

        self.assertIsNone(result)
        self.assertEqual(len(FakeConsoleChatBot.instances), 1)
        self.assertEqual(FakeConsoleChatBot.instances[0].calls, retry_count + 1)
