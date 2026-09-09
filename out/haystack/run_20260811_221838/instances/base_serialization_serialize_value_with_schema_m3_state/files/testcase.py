import random
import unittest

from haystack.utils.base_serialization import _serialize_value_with_schema


class GeneratedRecord:
    def __init__(self, seed, width):
        self.seed = seed
        self.width = width

    def to_dict(self):
        rolling = self.seed % 97
        values = []
        for index in range(self.width):
            rolling = (rolling * 37 + index * index + 11) % 211
            values.append({"slot": index, "signal": rolling})
        return {"values": values, "checksum": sum(item["signal"] for item in values) % 997}


class AttributeRecord:
    def __init__(self, seed, width):
        rolling = seed % 89
        self.samples = []
        for index in range(width):
            rolling = (rolling * 29 + index * 7 + 3) % 193
            self.samples.append((index, rolling))
        self.marker = sum(value for _, value in self.samples) % 383


class TestSerializeValueWithSchemaState(unittest.TestCase):
    def _check_result(self, result):
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result), {"serialization_schema", "serialized_data"})
        self.assertIsInstance(result["serialization_schema"], dict)

    def test_01_wide_generated_mapping(self):
        seed = sum((index + 1) * ord(char) for index, char in enumerate(self._testMethodName))
        payload = {}
        for index in range(sum((n % 3) + 1 for n in range(9))):
            signal = (seed * (index + 5) + index * index * 17) % 401
            key = chr(ord("a") + index)
            branch = signal % 5
            if branch == 0:
                payload[key] = signal
            elif branch == 1:
                payload[key] = signal / (index + 3)
            elif branch == 2:
                payload[key] = bool(signal % 2)
            elif branch == 3:
                payload[key] = None
            else:
                payload[key] = "".join(chr(97 + (signal + offset * 7) % 26) for offset in range(3 + index % 4))
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(len(result["serialized_data"]), len(payload))

    def test_02_generated_integer_list(self):
        rng = random.Random(sum(map(ord, self._testMethodName)))
        rolling = rng.randrange(503)
        payload = []
        for index in range(sum((n * n + 2) % 7 for n in range(14))):
            rolling = (rolling * 43 + rng.randrange(101) + index * 13) % 887
            payload.append(rolling - (index % 4) * 97)
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(len(result["serialized_data"]), len(payload))

    def test_03_generated_text_tuple(self):
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        seed = sum(ord(char) * (index + 7) for index, char in enumerate(self._testMethodName))
        payload = tuple(
            "".join(alphabet[(seed + slot * 11 + offset * offset) % len(alphabet)] for offset in range(2 + slot % 5))
            for slot in range(sum((n + 3) % 6 for n in range(11)))
        )
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(len(result["serialized_data"]), len(payload))

    def test_04_generated_integer_set(self):
        seed = sum((index + 5) * ord(char) for index, char in enumerate(self._testMethodName))
        payload = {(seed * (index + 9) + index**3) % 997 for index in range(sum(n % 5 for n in range(16)))}
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(set(result["serialized_data"]), payload)

    def test_05_nested_matrix(self):
        seed = sum(map(ord, self._testMethodName))
        payload = [
            [((row + 3) * (column + 5) * seed + row * row - column) % 509 for column in range(4 + row % 6)]
            for row in range(sum((n * 3) % 5 for n in range(5)))
        ]
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(len(result["serialized_data"]), len(payload))
        self.assertTrue(all(isinstance(row, list) for row in result["serialized_data"]))

    def test_06_layered_mapping(self):
        seed = sum((index + 2) * ord(char) for index, char in enumerate(self._testMethodName))
        payload = {
            f"g{group}": {
                f"v{slot}": (seed + group * 41 + slot * slot * 19) % 613
                for slot in range(3 + group % 2)
            }
            for group in range(3)
        }
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertTrue(all(isinstance(value, dict) for value in result["serialized_data"].values()))

    def test_07_to_dict_object(self):
        seed = sum(ord(char) * (index + 1) for index, char in enumerate(self._testMethodName))
        payload = GeneratedRecord(seed, sum((n + 1) % 4 for n in range(8)))
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertIsInstance(result["serialized_data"]["values"], list)
        self.assertGreater(len(result["serialized_data"]["values"]), 1)

    def test_08_attribute_object(self):
        seed = sum((index + 4) * ord(char) for index, char in enumerate(self._testMethodName))
        payload = AttributeRecord(seed, sum((n * n + 1) % 5 for n in range(9)))
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertIsInstance(result["serialized_data"]["samples"], list)
        self.assertTrue(all(isinstance(sample, list) for sample in result["serialized_data"]["samples"]))

    def test_09_generated_empty_collections(self):
        constructors = (list, tuple, set, dict)
        payload = {
            chr(107 + index): constructors[(index * index + index + 1) % len(constructors)]()
            for index in range(sum((n + 2) % 4 for n in range(4)))
        }
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertTrue(all(not value for value in result["serialized_data"].values()))

    def test_10_seeded_record_tree(self):
        rng = random.Random(sum((index + 9) * ord(char) for index, char in enumerate(self._testMethodName)))
        payload = {}
        for group in range(2):
            rolling = rng.randrange(701)
            records = {}
            for slot in range(2 + group % 3):
                rolling = (rolling * 31 + rng.randrange(83) + group * slot) % 919
                records[f"s{slot}"] = [rolling, rolling % 17 == 0]
            payload[f"r{group}"] = records
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(len(result["serialized_data"]), len(payload))

    def test_11_computed_primitive_spectrum(self):
        seed = sum(map(ord, self._testMethodName))
        payloads = [
            (seed * (index + 3) + index**2) % 541
            if index % 4 == 0
            else ((seed + index * 17) % 313) / (index + 2)
            if index % 4 == 1
            else bool((seed + index) % 3)
            if index % 4 == 2
            else None
            for index in range(sum((n + 1) % 5 for n in range(9)))
        ]
        results = [_serialize_value_with_schema(payload) for payload in payloads]
        self.assertTrue(all(set(result) == {"serialization_schema", "serialized_data"} for result in results))
        self.assertEqual(len(results), len(payloads))

    def test_12_mixed_collection_tree(self):
        seed = sum((index + 6) * ord(char) for index, char in enumerate(self._testMethodName))
        payload = {
            "sequence": tuple((seed + index * index * 23) % 467 for index in range(7)),
            "mapping": {chr(112 + index): (seed * (index + 2)) % 359 for index in range(5)},
            "nested": [[(seed + row * 31 + column * 7) % 271 for column in range(3)] for row in range(6)],
            "empty": [],
        }
        result = _serialize_value_with_schema(payload)
        self._check_result(result)
        self.assertEqual(set(result["serialized_data"]), set(payload))
