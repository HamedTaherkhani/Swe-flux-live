"""Runtime QA testcase for instance core_load_obj_s5_exceptions.

Exercises Kedro's dataset-class resolution machinery indirectly through
kedro.io.core.AbstractDataset.from_config over a programmatically built list
of dataset types. The list mixes entries that resolve successfully with
entries whose candidate class paths steer resolution through several
distinct failure outcomes (missing modules, missing attributes, malformed
paths), so the resolution helper is driven through all of its internal
error-handling branches many times.
"""

import unittest
import warnings

from kedro.io.core import AbstractDataset, DatasetError


def _build_dataset_types():
    types = []
    # Bare class names (no dot) that exist in no package.
    for i in range(6):
        types.append(f"GhostLoader{i:02d}")
    # Dotted paths rooted at packages that do not exist at all.
    for i in range(6):
        types.append(f"phantom_pkg_{i:02d}.loaders.Spook{i:02d}Dataset")
    # Dotted paths rooted at a real stdlib module lacking the attribute.
    for i in range(5):
        types.append(f"io.Phantom{i:02d}Dataset")
    # One entry that actually resolves.
    types.append("MemoryDataset")
    return types


class TestLoadObjExceptionsRuntime(unittest.TestCase):
    def test_traced_run(self):
        dataset_types = _build_dataset_types()
        self.assertEqual(len(dataset_types), 18)
        self.assertEqual(len(set(dataset_types)), 18)

        failures = []
        successes = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for name in dataset_types:
                entry = "ds_" + name.replace(".", "_")
                try:
                    dataset = AbstractDataset.from_config(
                        name=entry, config={"type": name}
                    )
                except DatasetError:
                    failures.append(name)
                else:
                    successes.append((entry, dataset))

        # Exactly one entry must resolve; all others must fail with the
        # catalog-level error type.
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), len(dataset_types) - 1)
        self.assertEqual(sorted(failures + ["MemoryDataset"]), sorted(dataset_types))

        entry, dataset = successes[0]
        self.assertEqual(entry, "ds_MemoryDataset")
        self.assertEqual(type(dataset).__name__, "MemoryDataset")
        dataset.save({"numbers": list(range(7))})
        self.assertEqual(dataset.load(), {"numbers": list(range(7))})
