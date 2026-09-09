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
        rng = random.Random(sum(ord(char) for char in "router-any-hard"))
        payload = {
            chr(ord("a") + index): [
                rng.randrange(13) if index % 3 else rng.randrange(-3, 13)
                for _ in range(index % 7 + 1)
            ]
            for index in range(7 * 11)
        }
        result = self._run_route(payload, Any)
        self.assertEqual(result["selected"], payload)

    def test_basic_integer_accepts_computed_scalar(self):
        value = sum(index * index for index in range(7 * 11))
        result = self._run_route(value, Union[str, int, float])
        self.assertEqual(result["selected"] % 2, value % 2)

    def test_basic_integer_rejects_generated_text(self):
        value = "".join(chr(ord("a") + index % 7) for index in range(7 * 11))
        with self.assertRaises(ValueError):
            self._run_route(value, int)

    def test_empty_parameterized_list(self):
        payload = [index for index in range(11) if index > 13]
        result = self._run_route(payload, Optional[list[int]])
        self.assertFalse(result["selected"])

    def test_long_homogeneous_sequence(self):
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate("sequence-hard")))
        payload = [rng.randrange(17) if index % 4 else rng.randrange(-5, 17) for index in range(7 * 11)]
        result = self._run_route(payload, Sequence[int])
        self.assertEqual(len(result["selected"]), len(payload))

    def test_sequence_with_late_mismatch(self):
        payload = [(index * index + 3) % 13 for index in range(7 * 11)]
        payload[-1] = "".join(chr(ord("q") + index) for index in range(5))
        with self.assertRaises(ValueError):
            self._run_route(payload, list[int])

    def test_generated_tuple_of_text(self):
        payload = tuple(
            chr(ord("d") + index % 9) * (index % 5 + 1) for index in range(7 * 13)
        )
        result = self._run_route(payload, tuple[str])
        self.assertIsInstance(result["selected"], tuple)

    def test_non_sequence_rejected(self):
        payload = sum((index + 1) * (index % 3 + 1) for index in range(7 * 13))
        with self.assertRaises(ValueError):
            self._run_route(payload, Sequence[int])

    def test_empty_parameterized_mapping(self):
        payload = {index: index for index in range(11) if index > 13}
        result = self._run_route(payload, dict[int, int])
        self.assertEqual(len(result["selected"]), 0)

    def test_large_homogeneous_mapping(self):
        payload = {
            f"k{index:x}": (index * index + 7) % 17 if index % 2 else -(index % 9)
            for index in range(7 * 11)
        }
        result = self._run_route(payload, Union[Mapping[str, int], dict[str, int]])
        self.assertEqual(set(result["selected"]), set(payload))

    def test_mapping_with_nested_sequences(self):
        payload = {
            chr(ord("a") + outer): [
                {f"n{inner}": (outer * inner + inner * inner) % 17 for inner in range(outer % 5 + 2)}
                for _ in range(outer % 4 + 2)
            ]
            for outer in range(13)
        }
        result = self._run_route(payload, dict[str, list[dict[str, int]]])
        self.assertEqual(sum(map(len, result["selected"].values())), sum(map(len, payload.values())))

    def test_sequence_of_generated_mappings(self):
        payload = [
            {
                f"v{inner}": [(outer + inner + sub) % 13 for sub in range(outer % 4 + 1)]
                for inner in range(outer % 6 + 2)
            }
            for outer in range(7 * 11)
        ]
        result = self._run_route(payload, list[dict[str, list[int]]])
        self.assertEqual(len(result["selected"]), len(payload))

    def test_union_uses_later_alternative(self):
        payload = "".join(chr(ord("m") + index % 7) for index in range(7 * 11))
        result = self._run_route(payload, Union[int, float, str])
        self.assertTrue(result["selected"].startswith(payload[:3]))

    def test_optional_accepts_none(self):
        payload = next((index for index in range(11) if index > 13), None)
        result = self._run_route(payload, Optional[list[int]])
        self.assertIsNone(result["selected"])

    def test_unsupported_parameterized_set_rejected(self):
        payload = {(index * index + 3) % 17 for index in range(7 * 13)}
        with self.assertRaises(ValueError):
            self._run_route(payload, set[int])