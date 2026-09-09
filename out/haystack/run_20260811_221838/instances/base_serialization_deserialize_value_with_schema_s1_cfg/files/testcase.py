import random
import unittest

from haystack.utils.base_serialization import _deserialize_value_with_schema


class TestDeserializeValueWithSchemaCFG(unittest.TestCase):
    def test_programmatic_nested_object_path(self):
        rng = random.Random(sum(ord(char) for char in "schema-control-flow"))
        outer_size = len("programmatically-sized-root")
        nested_position = len("branching") - 2
        outer_fields = [f"field_{index}_{rng.randrange(10_000):04d}" for index in range(outer_size)]

        inner_size = len("data-dependent-inner-object-with-many-fields")
        inner_fields = [f"item_{index}_{rng.randrange(10_000):04d}" for index in range(inner_size)]
        selectors = [rng.randrange(2, 97) for _ in inner_fields]
        inner_data = {
            field: (selector * (index + 3)) - (index % 5)
            for index, (field, selector) in enumerate(zip(inner_fields, selectors))
        }
        inner_properties = {
            field: {"type": "integer"}
            for index, (field, selector) in enumerate(zip(inner_fields, selectors))
            if (selector + index * index) % 4 != 0
        }

        root_data = {}
        root_properties = {}
        for index, field in enumerate(outer_fields):
            if index == nested_position:
                root_data[field] = inner_data
                root_properties[field] = {"type": "object", "properties": inner_properties}
            else:
                root_data[field] = (selectors[index % inner_size] << (index % 3)) - index
                root_properties[field] = {"type": ("integer", "number", "string", "boolean")[index % 4]}

        payload = {
            "serialization_schema": {"type": "object", "properties": root_properties},
            "serialized_data": root_data,
        }
        result = _deserialize_value_with_schema(payload)

        nested_key = outer_fields[nested_position]
        self.assertEqual(len(result), len(root_data))
        self.assertEqual(set(result[nested_key]), set(inner_properties))
        self.assertTrue(all(result[nested_key][key] == inner_data[key] for key in result[nested_key]))
