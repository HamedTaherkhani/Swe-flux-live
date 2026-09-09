from __future__ import annotations

import unittest
from typing import Annotated

from fastapi._compat import shared


class RuntimeSequenceGraphTest(unittest.TestCase):
    def test_generated_annotation_matrix(self) -> None:
        scalars = (int, str, bytes, float, bool, complex)
        containers = (list, tuple, set, frozenset)
        annotations = []

        for index in range(24):
            scalar = scalars[(index * index + 3 * index + 1) % len(scalars)]
            annotation = containers[(index * 5 + 2) % len(containers)][scalar]
            if index % 6 == 0:
                annotation = list[annotation]
            if index % 5 == 0:
                annotation = annotation | dict[str, scalar]
            if index % 3 == 0:
                annotation = annotation | None
            if index % 4 == 0:
                annotation = Annotated[annotation, f"marker-{(index * 7) % 11}"]
            annotations.append(annotation)

        probes = (
            shared.annotation_is_pydantic_v1,
            shared.field_annotation_is_scalar_sequence,
            shared.is_bytes_sequence_annotation,
            shared.is_uploadfile_sequence_annotation,
        )
        outcomes = [probe(annotation) for annotation in annotations for probe in probes]

        self.assertEqual(len(outcomes), len(annotations) * len(probes))
        self.assertTrue(all(isinstance(outcome, bool) for outcome in outcomes))
        self.assertTrue(any(outcomes))
        self.assertFalse(all(outcomes))
