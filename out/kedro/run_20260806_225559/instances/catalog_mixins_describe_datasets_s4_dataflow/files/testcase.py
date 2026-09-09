import random
import unittest

from kedro.framework.context.catalog_mixins import CatalogCommandsMixin
from kedro.framework.context.context import compose_classes
from kedro.io import DataCatalog
from kedro.pipeline import Node, Pipeline


class TestDescribeDatasetsDataFlow(unittest.TestCase):
    def test_seeded_mixed_pipeline_descriptions(self):
        rng = random.Random(0xCADA10)
        prefixes = ("stored", "factory", "runtime")
        dataset_names = [
            f"{prefixes[(index * index + rng.randrange(9)) % len(prefixes)]}_"
            f"{index:02x}_{rng.randrange(1 << 14):04x}"
            for index in range(48)
        ]

        catalog_config = {
            name: {"type": "MemoryDataset"}
            for name in dataset_names
            if name.startswith("stored_")
        }
        catalog_config["factory_{token}"] = {"type": "MemoryDataset"}
        catalog_class = compose_classes(DataCatalog, CatalogCommandsMixin)
        catalog = catalog_class.from_config(catalog=catalog_config)

        def identity(value):
            return value

        nodes = [
            Node(
                func=identity,
                inputs=dataset_names[index],
                outputs=dataset_names[index + 1],
                name=f"generated_node_{index:02x}",
            )
            for index in range(0, len(dataset_names) - 1, 2)
        ]
        primary = Pipeline(nodes)
        reduced = Pipeline(nodes[index] for index in range(len(nodes)) if index % 3)

        choices = (primary, reduced, "missing_" + dataset_names[0])
        mixed = [choices[rng.randrange(len(choices))] for _ in range(21)]
        mixed.extend((primary, "absent_" + dataset_names[-1], reduced))
        rng.shuffle(mixed)

        first = CatalogCommandsMixin.describe_datasets(catalog, mixed)
        second = CatalogCommandsMixin.describe_datasets(catalog, primary)

        self.assertGreater(len(first), len(mixed) // 2)
        self.assertEqual(set(second), {"pipeline_0"})
        self.assertTrue(
            all(
                set(description) == {"datasets", "factories", "defaults"}
                for description in first.values()
            )
        )
