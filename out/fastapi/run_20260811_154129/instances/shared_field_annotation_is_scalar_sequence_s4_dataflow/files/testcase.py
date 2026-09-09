from functools import reduce
import operator
from typing import Annotated
import unittest

from fastapi._compat.shared import field_annotation_is_scalar_sequence


class TestScalarSequenceDataFlow(unittest.TestCase):
    def test_generated_annotation_families(self) -> None:
        scalar_types = [
            type(f"GeneratedScalar{index}", (), {})
            for index in range(sum((3, 5, 7, 11)))
        ]
        mixed_members = [
            list[item] if (index * index + index) % 3 else item
            for index, item in enumerate(scalar_types)
        ]
        rich_union = reduce(operator.or_, mixed_members)

        hostile_index = sum(ord(char) for char in "sequence") % len(scalar_types)
        hostile_members = [
            list[item] if index % 4 == 1 else item
            for index, item in enumerate(scalar_types)
        ]
        hostile_members.insert(hostile_index, list[dict[str, object]])
        hostile_union = reduce(operator.or_, hostile_members)
        scalar_union = reduce(operator.or_, scalar_types)

        annotations = [
            Annotated[rich_union, object()],
            rich_union,
            hostile_union,
            scalar_union,
            list[scalar_types[hostile_index]],
            list[dict[str, object]],
        ]
        results = [
            field_annotation_is_scalar_sequence(annotation)
            for annotation in annotations
        ]

        self.assertEqual(len(results), len(annotations))
        self.assertTrue(any(results))
        self.assertTrue(any(not result for result in results))
        self.assertEqual(results[0], results[1])

