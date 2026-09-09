import json
import types
import unittest

from src.llamafactory.api import chat


class TestChatProcessRequestS5Exceptions(unittest.TestCase):
    def test_jsondecodeerror_then_runtimeerror_propagates(self):
        original_dictify = chat.dictify
        original_http_exception = chat.HTTPException
        original_is_env_enabled = chat.is_env_enabled
        original_status = chat.status

        def raising_dictify(_value):
            raise json.JSONDecodeError("forced decode failure", "{}", 1)

        def runtime_http_exception(*, status_code, detail):
            return RuntimeError(f"{status_code}: {detail}")

        try:
            chat.dictify = raising_dictify
            chat.HTTPException = runtime_http_exception
            chat.is_env_enabled = lambda *_args, **_kwargs: False
            chat.status = types.SimpleNamespace(HTTP_400_BAD_REQUEST=400)

            request = types.SimpleNamespace(
                messages=[types.SimpleNamespace(role=chat.Role.USER, content="hello", tool_calls=None)],
                tools=[types.SimpleNamespace(function=object())],
            )

            with self.assertRaises(RuntimeError) as caught:
                chat._process_request(request)
        finally:
            chat.dictify = original_dictify
            chat.HTTPException = original_http_exception
            chat.is_env_enabled = original_is_env_enabled
            chat.status = original_status

        self.assertEqual(str(caught.exception), "400: Invalid tools")
