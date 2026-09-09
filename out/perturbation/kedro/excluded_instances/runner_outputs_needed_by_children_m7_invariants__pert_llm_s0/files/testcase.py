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
        rng = random.Random(int.from_bytes(b"runner-state-m7-hard-variant-one", "big"))
        group_count = len("kappa-beta")
        outputs_per_group = len("tracking-observation-heterogeneous-loop-x")
        token_width = len("checksum-token-bucket-width")
        alphabet = string.ascii_lowercase + string.digits + string.ascii_uppercase

        catalog = DataCatalog()
        nodes = []
        consumed = []

        def unavailable_parent():
            raise AssertionError("an upstream node with existing outputs was executed")

        def produce_refresh_value():
            return (token_width + 1) * group_count + outputs_per_group

        def consume(*values):
            consumed.append(tuple(values))

        for group_index in range(group_count):
            output_names = []
            for slot_index in range(outputs_per_group):
                token = "".join(rng.choice(alphabet) for _ in range(token_width))
                dataset_name = (
                    f"vault_{group_index:03x}_{slot_index:03x}_{token}"
                )
                output_names.append(dataset_name)
                catalog[dataset_name] = ExistingDataset(
                    ((group_index + 1) * (slot_index + 1))
                    + token_width
                    + (slot_index % (group_index + 3 + (token_width % 5)))
                )

            nodes.append(
                node(
                    unavailable_parent,
                    None,
                    output_names,
                    name=f"emitter_{group_index:03x}",
                )
            )
            nodes.append(
                node(
                    consume,
                    output_names,
                    None,
                    name=f"sink_{group_index:03x}",
                )
            )

        refresh_token = "".join(
            rng.choice(alphabet) for _ in range(token_width)
        )
        refresh_name = f"bootstrap_{refresh_token}"
        nodes.extend(
            [
                node(
                    produce_refresh_value,
                    None,
                    refresh_name,
                    name="bootstrap_materializer",
                ),
                node(consume, refresh_name, None, name="bootstrap_consumer"),
            ]
        )

        result = SequentialRunner().run(
            pipeline(nodes), catalog, only_missing_outputs=True
        )

        self.assertEqual(result, {})
        self.assertGreater(len(consumed), group_count)
        self.assertTrue(all(all(value > 0 for value in batch) for batch in consumed))
