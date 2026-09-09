from __future__ import annotations

import unittest

from kedro.io import AbstractDataset


class RuntimeDataSet(AbstractDataset):
    def __init__(
        self,
        payload: tuple[int, ...],
        marker: int,
        version=None,
        metadata=None,
    ) -> None:
        self.payload = payload
        self.marker = marker
        self.version = version
        self.metadata = metadata

    def load(self) -> tuple[int, ...]:
        return self.payload

    def save(self, data: tuple[int, ...]) -> None:
        self.payload = data

    def _describe(self) -> dict:
        return {"marker": self.marker}


class TestDatasetDefinitionControlFlow(unittest.TestCase):
    def test_generated_configurations(self) -> None:
        datasets = []
        qualified_type = ".".join(
            (RuntimeDataSet.__module__, RuntimeDataSet.__qualname__)
        )

        for index in range(sum(divmod(89, 4))):
            values = tuple(
                ((index + 3) * (offset + 5) + offset * offset) % 97
                for offset in range(16 + index % 5)
            )
            selector = (sum(values[::3]) + index) % 4

            if selector == 0:
                config = {"type": RuntimeDataSet}
            elif selector == 1:
                config = {"type": "MemoryDataset", "data": list(values)}
            else:
                config = {"type": qualified_type}

            if selector != 1:
                config.update(
                    {
                        "payload": values,
                        "marker": sum(value ^ index for value in values),
                        "versioned": (index * 2 + selector) % 5 != 0,
                    }
                )
            if (index * index + selector) % 5 in {0, 2, 4}:
                config["version"] = f"reserved-{index * 13 + selector}"

            dataset = AbstractDataset.from_config(
                name=f"generated_{index}_{selector}",
                config=config,
                load_version=f"load-{index % 7}",
                save_version=f"save-{(index * 11 + selector) % 23}",
            )
            datasets.append(dataset)

        self.assertGreater(len(datasets), len(datasets[0].load()))
        self.assertEqual(
            sum(isinstance(dataset, RuntimeDataSet) for dataset in datasets)
            + sum(dataset.__class__.__name__ == "MemoryDataset" for dataset in datasets),
            len(datasets),
        )
