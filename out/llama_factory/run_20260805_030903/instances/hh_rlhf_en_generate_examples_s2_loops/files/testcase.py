import importlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import datasets


class TestHhRlhfDatasetGeneration(unittest.TestCase):
    def test_seeded_dialogues_through_builder_entrypoint(self):
        rng = random.Random(sum(map(ord, "hh-rlhf-runtime")))
        baseline_turns = ord("R") % 17 + 4
        turn_span = ord("d") // 10
        record_count = ord("q") % 7 + 4
        records = []

        for record_index in range(record_count):
            turn_count = baseline_turns + rng.randrange(turn_span)
            dialogue = "".join(
                (
                    f"\n\nHuman: prompt-{record_index}-{turn_index}-{rng.randrange(10000)}"
                    f"\n\nAssistant: response-{record_index}-{turn_index}-{rng.randrange(10000)}"
                )
                for turn_index in range(turn_count)
            )
            records.append(
                {
                    "chosen": dialogue + f"\n\nHuman: final-{record_index}\n\nAssistant: accepted-{record_index}",
                    "rejected": dialogue + f"\n\nHuman: final-{record_index}\n\nAssistant: declined-{record_index}",
                }
            )

        module = importlib.import_module("data.hh_rlhf_en.hh_rlhf_en")
        builder_class = next(
            value
            for value in vars(module).values()
            if isinstance(value, type) and value.__module__ == module.__name__
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "seeded-dialogues.jsonl"
            source_path.write_text(
                "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
                encoding="utf-8",
            )

            builder = builder_class(cache_dir=str(temp_path / "cache"))
            download_manager = datasets.DownloadManager()
            local_splits = {
                "train": [str(source_path)],
                "test": [str(source_path)],
            }
            with mock.patch.object(
                download_manager,
                "download_and_extract",
                return_value=local_splits,
            ):
                builder.download_and_prepare(dl_manager=download_manager)

            generated = builder.as_dataset()

        self.assertEqual(set(generated), {"train", "test"})
        self.assertTrue(all(len(generated[split]) == len(records) for split in generated))
        history_sizes = [len(example["history"]) for example in generated["train"]]
        self.assertTrue(all(size >= baseline_turns for size in history_sizes))
        self.assertGreater(len(set(history_sizes)), 1)
