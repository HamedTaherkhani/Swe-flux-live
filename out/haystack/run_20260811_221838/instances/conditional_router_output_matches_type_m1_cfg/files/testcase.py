import random
import unittest
from typing import Any, Mapping, Optional, Sequence, Union

from haystack.components.routers import ConditionalRouter


class TestConditionalRouterOutputTypes(unittest.TestCase):
    def _run_route(self, payload, output_type):
        router = ConditionalRouter(
            [
                {
                    "condition": "{{ enabled }}",
                    "output": "{{ payload }}",
                    "output_name": "selected",
                    "output_type": output_type,
                }
            ],
            validate_output_type=True,
        )
        return router.run(enabled=True, payload=payload)

    def test_any_accepts_programmatic_nested_value(self):
        rng = random.Random(sum(ord(char) for char in "router-any"))
        payload = {
            chr(ord("a") + index): [rng.randrange(7) for _ in range(index % 5)]
            for index in range(3 * 7)
        }
        result = self._run_route(payload, Any)
        self.assertEqual(result["selected"], payload)

    def test_basic_integer_accepts_computed_scalar(self):
        value = sum(index * index for index in range(3 * 7))
        result = self._run_route(value, int)
        self.assertEqual(result["selected"] % 2, value % 2)

    def test_basic_integer_rejects_generated_text(self):
        value = "".join(chr(ord("a") + index % 5) for index in range(3 * 7))
        with self.assertRaises(ValueError):
            self._run_route(value, int)

    def test_empty_parameterized_list(self):
        payload = [index for index in range(7) if index > 8]
        result = self._run_route(payload, list[int])
        self.assertFalse(result["selected"])

    def test_long_homogeneous_sequence(self):
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate("sequence")))
        payload = [rng.randrange(9) for _ in range(3 * 7)]
        result = self._run_route(payload, Sequence[int])
        self.assertEqual(len(result["selected"]), len(payload))

    def test_sequence_with_late_mismatch(self):
        payload = [index % 7 for index in range(3 * 7)]
        payload[-1] = "".join(chr(ord("q") + index) for index in range(3))
        with self.assertRaises(ValueError):
            self._run_route(payload, list[int])

    def test_generated_tuple_of_text(self):
        payload = tuple(chr(ord("d") + index % 6) * (index % 3 + 1) for index in range(4 * 5))
        result = self._run_route(payload, tuple[str])
        self.assertIsInstance(result["selected"], tuple)

    def test_non_sequence_rejected(self):
        payload = sum(index + 1 for index in range(4 * 5))
        with self.assertRaises(ValueError):
            self._run_route(payload, Sequence[int])

    def test_empty_parameterized_mapping(self):
        payload = {index: index for index in range(7) if index > 8}
        result = self._run_route(payload, dict[int, int])
        self.assertEqual(len(result["selected"]), 0)

    def test_large_homogeneous_mapping(self):
        payload = {f"k{index:x}": (index * index + 3) % 7 for index in range(3 * 7)}
        result = self._run_route(payload, Mapping[str, int])
        self.assertEqual(set(result["selected"]), set(payload))

    def test_mapping_with_nested_sequences(self):
        payload = {
            chr(ord("a") + outer): [(outer + inner * inner) % 9 for inner in range(outer + 2)]
            for outer in range(7)
        }
        result = self._run_route(payload, dict[str, list[int]])
        self.assertEqual(sum(map(len, result["selected"].values())), sum(map(len, payload.values())))

    def test_sequence_of_generated_mappings(self):
        payload = [
            {f"v{inner}": (outer + inner) % 8 for inner in range(outer % 4 + 1)}
            for outer in range(3 * 5)
        ]
        result = self._run_route(payload, list[dict[str, int]])
        self.assertEqual(len(result["selected"]), len(payload))

    def test_union_uses_later_alternative(self):
        payload = "".join(chr(ord("m") + index % 4) for index in range(3 * 7))
        result = self._run_route(payload, Union[int, str])
        self.assertTrue(result["selected"].startswith(payload[:3]))

    def test_optional_accepts_none(self):
        payload = next((index for index in range(7) if index > 8), None)
        result = self._run_route(payload, Optional[list[int]])
        self.assertIsNone(result["selected"])

    def test_unsupported_parameterized_set_rejected(self):
        payload = {index % 9 for index in range(4 * 5)}
        with self.assertRaises(ValueError):
            self._run_route(payload, set[int])
