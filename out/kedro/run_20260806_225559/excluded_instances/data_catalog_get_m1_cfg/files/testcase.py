from __future__ import annotations

from pathlib import PurePosixPath
import unittest

from kedro.io import AbstractVersionedDataset, DataCatalog, Version


class GeneratedVersionedDataset(AbstractVersionedDataset):
    def __init__(self) -> None:
        super().__init__(
            filepath=PurePosixPath("unused/generated"),
            version=Version("initial", None),
        )

    def load(self) -> str | None:
        return self._version.load if self._version else None

    def save(self, data: str) -> None:
        pass

    def _describe(self) -> dict:
        return {}


class TestCatalogIndirectControlFlow(unittest.TestCase):
    def test_generated_catalog_accesses(self) -> None:
        width = sum(divmod(131, 5))
        names = [
            f"generated_{index}_{(index * index + 3 * index) % 17}"
            for index in range(width)
        ]
        config = {
            name: {
                "type": "MemoryDataset",
                "data": [
                    ((index + 7) * (offset + 11) + offset * offset) % 101
                    for offset in range(18 + index % 7)
                ],
            }
            for index, name in enumerate(names)
        }
        config["factory_{bucket}_{token}"] = {
            "type": "MemoryDataset",
            "data": "{bucket}:{token}",
        }
        catalog = DataCatalog.from_config(config)

        loaded = [catalog.load(name) for name in names]
        existing = [catalog.exists(name) for name in reversed(names)]
        factory_names = [
            f"factory_{(index * 13 + 5) % 19}_{(index**3 + 7) % 23}"
            for index in range(sum(divmod(47, 5)))
        ]
        patterned = [catalog.exists(name) for name in factory_names]
        absent_names = [
            f"absent_{(index * index + 29) % 31}_{index}"
            for index in range(sum(divmod(43, 7)))
        ]
        absent = [catalog.exists(name) for name in absent_names]
        versioned_catalog = DataCatalog(
            datasets={"versioned": GeneratedVersionedDataset()}
        )
        requested_version = ".".join(
            str((value * value + 3) % 29) for value in range(len(absent_names))
        )
        loaded_version = versioned_catalog.load(
            next(iter(versioned_catalog.keys())),
            version=requested_version,
        )

        self.assertEqual(len(loaded), len(names))
        self.assertTrue(all(existing))
        self.assertTrue(all(patterned))
        self.assertFalse(any(absent))
        self.assertEqual(loaded_version, requested_version)
        self.assertGreater(
            sum(len(values) for values in loaded),
            sum(len(name) for name in names),
        )
