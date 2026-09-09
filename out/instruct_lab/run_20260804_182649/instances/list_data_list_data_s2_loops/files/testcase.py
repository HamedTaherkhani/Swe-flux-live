import random
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from instructlab import lab


class TestDatasetListingTraversal(unittest.TestCase):
    def test_generated_directory_forest_through_cli(self):
        seed = sum((index + 3) * (index + 5) for index in range(9))
        rng = random.Random(seed)

        with tempfile.TemporaryDirectory() as temporary_directory:
            dataset_root = Path(temporary_directory) / "generated-datasets"
            dataset_root.mkdir()
            frontier = [dataset_root]

            for depth in range(4):
                next_frontier = []
                for parent_index, parent in enumerate(frontier):
                    child_total = 1 + (
                        depth * 7 + parent_index * 3 + rng.randrange(17)
                    ) % 3
                    for branch in range(child_total):
                        token = rng.randrange(100_000)
                        child = parent / (
                            f"run_{depth}_{parent_index}_{branch}_{token:05d}"
                        )
                        child.mkdir()
                        next_frontier.append(child)

                        record_total = 1 + (token + depth + branch) % 3
                        for record_index in range(record_total):
                            payload = (
                                f'{{"index": {record_index}, '
                                f'"token": {(token * (record_index + 3)) % 100_003}}}\n'
                            )
                            (child / f"records_{record_index}_{token:05d}.jsonl").write_text(
                                payload, encoding="utf-8"
                            )
                        if (token + parent_index) % 2 == 0:
                            (child / f"notes_{token:05d}.txt").write_text(
                                "ignored\n", encoding="utf-8"
                            )
                frontier = next_frontier

            result = CliRunner().invoke(
                lab.ilab,
                [
                    "--config=DEFAULT",
                    "data",
                    "list",
                    "--dataset-dirs",
                    str(dataset_root),
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Dataset", result.output)
            self.assertIn("records_", result.output)
            self.assertNotIn("notes_", result.output)
