from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from haystack.components.connectors import OpenAPIServiceConnector
from haystack.dataclasses import ChatMessage, ToolCall


class _RecordedOperation:
    def __init__(self, raw_element, seed):
        self.operation = SimpleNamespace(__self__=SimpleNamespace(raw_element=raw_element))
        self.seed = seed
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        packed = sum(len(value) for value in kwargs.values() if isinstance(value, dict))
        return {"token": (self.seed * 97 + packed * 13) % 1009, "packed": packed}


class TestOpenAPIInvokeDataFlow(TestCase):
    def _descriptor(self, seed, url_count, body_count, mode):
        method_name = f"operation_{seed}_{mode}"
        arguments = {}
        parameters = []

        for index in range(url_count):
            key = f"route_{seed}_{index}"
            required = index % 7 == 2
            if mode == "missing_url" and index == url_count - 1:
                required = True
            elif mode == "falsey_url" and index % 5 == 1:
                required = False
                arguments[key] = 0
            else:
                arguments[key] = ((seed + 11) * (index + 3)) % 997 + 1
            parameters.append({"name": key, "required": required})

        if mode == "missing_url":
            arguments.pop(parameters[-1]["name"], None)

        operation = {"parameters": parameters}
        if body_count:
            properties = {}
            required_body = []
            for index in range(body_count):
                key = f"payload_{seed}_{index}"
                properties[key] = {"type": "integer"}
                is_required = index % 8 == 3
                if mode == "missing_body" and index == body_count - 1:
                    is_required = True
                if is_required:
                    required_body.append(key)
                if mode == "falsey_body" and index % 6 == 2:
                    if key in required_body:
                        required_body.remove(key)
                    arguments[key] = None
                else:
                    arguments[key] = ((seed + 5) ** 2 + index * 17) % 991 + 1
            if mode == "missing_body":
                arguments.pop(next(reversed(properties)), None)
            operation["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": {"properties": properties, "required": required_body}
                    }
                }
            }

        if mode == "empty_args":
            arguments.clear()
        return method_name, arguments, operation

    def _run_scenario(self, definitions):
        service = SimpleNamespace(raw_element={}, info=SimpleNamespace(title="generated"))
        tool_calls = []
        recorders = []
        expected_error = any(mode in {"missing_url", "missing_body", "unknown", "empty_args"} for *_, mode in definitions)

        for seed, url_count, body_count, mode in definitions:
            method_name, arguments, operation = self._descriptor(seed, url_count, body_count, mode)
            tool_calls.append(ToolCall(tool_name=method_name, arguments=arguments))
            if mode != "unknown":
                recorder = _RecordedOperation(operation, seed)
                setattr(service, f"call_{method_name}", recorder)
                recorders.append(recorder)

        connector = OpenAPIServiceConnector()
        message = ChatMessage.from_assistant(tool_calls=tool_calls)
        with patch("haystack.components.connectors.openapi_service.OpenAPI", return_value=service):
            if expected_error:
                with self.assertRaises((ValueError, RuntimeError)):
                    connector.run(messages=[message], service_openapi_spec={"seeded": True})
                self.assertLess(sum(len(item.calls) for item in recorders), len(tool_calls))
            else:
                result = connector.run(messages=[message], service_openapi_spec={"seeded": True})
                self.assertEqual(len(result["service_response"]), len(tool_calls))
                self.assertTrue(all(item.calls for item in recorders))

    def test_url_parameter_sweep(self):
        self._run_scenario([(13, 19, 0, "normal")])

    def test_request_body_sweep(self):
        self._run_scenario([(17, 0, 21, "normal")])

    def test_mixed_parameter_groups(self):
        self._run_scenario([(23, 17, 18, "normal")])

    def test_optional_falsey_url_values(self):
        self._run_scenario([(29, 23, 0, "falsey_url")])

    def test_optional_falsey_body_values(self):
        self._run_scenario([(31, 0, 24, "falsey_body")])

    def test_late_missing_url_requirement(self):
        self._run_scenario([(37, 20, 0, "missing_url")])

    def test_late_missing_body_requirement(self):
        self._run_scenario([(41, 4, 22, "missing_body")])

    def test_unknown_generated_operation(self):
        self._run_scenario([(43, 16, 0, "unknown")])

    def test_empty_generated_arguments(self):
        self._run_scenario([(47, 18, 0, "empty_args")])

    def test_three_operations_with_different_shapes(self):
        self._run_scenario(
            [
                (53, 16, 0, "normal"),
                (59, 3, 19, "normal"),
                (61, 15, 17, "falsey_body"),
            ]
        )

    def test_schema_with_sparse_required_fields(self):
        self._run_scenario([(67, 18, 27, "normal")])

    def test_four_sequential_operations(self):
        self._run_scenario(
            [
                (71, 15, 2, "normal"),
                (73, 2, 16, "falsey_url"),
                (79, 17, 3, "normal"),
                (83, 1, 18, "falsey_body"),
            ]
        )
