import random
import string
import unittest

from kedro.io import AbstractDataset, DataCatalog
from kedro.pipeline import node, pipeline
from kedro.runner import SequentialRunner


class ExistingDataset(AbstractDataset):
    def __init__(self, value):
        self._value = value

    def _load(self):
        return self._value

    def _save(self, data):
        self._value = data

    def _exists(self):
        return self._value is not None

    def _describe(self):
        return {}


class TestOutputsNeededByChildrenInvariants(unittest.TestCase):
    def test_seeded_existing_fanout_outputs(self):
        rng = random.Random(int.from_bytes(b"runner-state", "big"))
        group_count = len("flux")
        outputs_per_group = len("observation-window-for-loops")
        token_width = len("checksumtoken")
        alphabet = string.ascii_lowercase + string.digits

        catalog = DataCatalog()
        nodes = []
        consumed = []

        def unavailable_parent():
            raise AssertionError("an upstream node with existing outputs was executed")

        def produce_refresh_value():
            return token_width * group_count

        def consume(*values):
            consumed.append(tuple(values))

        for group_index in range(group_count):
            output_names = []
            for slot_index in range(outputs_per_group):
                token = "".join(rng.choice(alphabet) for _ in range(token_width))
                dataset_name = (
                    f"cache_{group_index:02x}_{slot_index:02x}_{token}"
                )
                output_names.append(dataset_name)
                catalog[dataset_name] = ExistingDataset(
                    (group_index + 1) * (slot_index + token_width)
                )

            nodes.append(
                node(
                    unavailable_parent,
                    None,
                    output_names,
                    name=f"materializer_{group_index:02x}",
                )
            )
            nodes.append(
                node(
                    consume,
                    output_names,
                    None,
                    name=f"consumer_{group_index:02x}",
                )
            )

        refresh_token = "".join(
            rng.choice(alphabet) for _ in range(token_width)
        )
        refresh_name = f"refresh_{refresh_token}"
        nodes.extend(
            [
                node(
                    produce_refresh_value,
                    None,
                    refresh_name,
                    name="refresh_materializer",
                ),
                node(consume, refresh_name, None, name="refresh_consumer"),
            ]
        )

        result = SequentialRunner().run(
            pipeline(nodes), catalog, only_missing_outputs=True
        )

        self.assertEqual(result, {})
        self.assertGreater(len(consumed), group_count)
        self.assertTrue(all(all(value > 0 for value in batch) for batch in consumed))
