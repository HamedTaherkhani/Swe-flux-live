from __future__ import annotations

import unittest

from kedro.io.catalog_config_resolver import CatalogConfigResolver


class TestCatalogConfigResolverCallGraph(unittest.TestCase):
    def test_generated_catalog_construction(self) -> None:
        span = sum(range(4, 13))
        credential_names = [f"credential_{index:02d}" for index in range(span)]
        credentials = {
            name: {
                "token": f"{index * index + 17:x}",
                "region": f"zone-{(index * 7) % 11}",
            }
            for index, name in enumerate(credential_names)
        }

        config = {}
        for index in range(span):
            is_factory = (index * index + index) % 5 in {0, 2}
            dataset_name = (
                f"factory_{index:02d}_{{name}}"
                if is_factory
                else f"dataset_{index:02d}"
            )
            primary = credential_names[(index * 13 + 5) % span]
            secondary = credential_names[(index * 17 + 9) % span]
            config[dataset_name] = {
                "type": "kedro.io.MemoryDataset",
                "credentials": primary,
                "metadata": {
                    "mirror": {"credentials": secondary},
                    "label": f"{{name}}-{index:02d}" if is_factory else f"item-{index:02d}",
                },
            }

        resolver = CatalogConfigResolver(
            config=config,
            credentials=credentials,
            default_runtime_patterns={
                "{fallback}": {"type": "kedro.io.MemoryDataset"}
            },
        )

        self.assertEqual(len(resolver.config) + len(resolver.list_patterns()), span + 1)
        self.assertTrue(
            all(
                isinstance(dataset_config["credentials"], dict)
                for dataset_config in resolver.config.values()
            )
        )

