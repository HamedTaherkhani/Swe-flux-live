import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.llamafactory.data.loader import _load_single_dataset
from src.llamafactory.data.parser import DatasetAttr


class FakeDataset:
    def __init__(self, items, is_iterable=False):
        self.items = list(items)
        self.is_iterable = is_iterable

    def __len__(self):
        return len(self.items)

    def select(self, indexes):
        if isinstance(indexes, range):
            indexes = list(indexes)
        return FakeDataset([self.items[int(i) % len(self.items)] for i in indexes], is_iterable=self.is_iterable)

    def to_iterable_dataset(self, num_shards):
        return FakeDataset(self.items, is_iterable=True)


class TestLoadSingleDatasetS1CFG(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="loader_s1_cfg_")
        self.data_dir = os.path.join(self.tmpdir, "datasets")
        os.makedirs(self.data_dir, exist_ok=True)

        self.sample_dir = os.path.join(self.data_dir, "sample_dir")
        os.makedirs(self.sample_dir, exist_ok=True)
        for file_name in ("a.json", "b.json"):
            with open(os.path.join(self.sample_dir, file_name), "w", encoding="utf-8") as handle:
                handle.write("{\"text\": \"ok\"}\n")

        self.single_file = os.path.join(self.data_dir, "single.json")
        with open(self.single_file, "w", encoding="utf-8") as handle:
            handle.write("{\"text\": \"single\"}\n")

        self.model_args = SimpleNamespace(
            cache_dir=None,
            hf_hub_token=None,
            trust_remote_code=False,
            ms_hub_token=None,
            om_hub_token=None,
        )
        self.training_args = SimpleNamespace(dataloader_num_workers=2)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cfg_second_invocation_line_sequence(self):
        calls = []

        def fake_load_dataset(**kwargs):
            calls.append(kwargs)
            return FakeDataset([{"id": 0}, {"id": 1}, {"id": 2}])

        def passthrough_align(dataset, dataset_attr, data_args, training_args):
            return dataset

        np.random.seed(7)

        with (
            patch("src.llamafactory.data.loader.load_dataset", side_effect=fake_load_dataset),
            patch("src.llamafactory.data.loader.align_dataset", side_effect=passthrough_align),
        ):
            # Invocation 1: file path, no sampling/truncation.
            data_args_first = SimpleNamespace(
                dataset_dir=self.data_dir,
                streaming=False,
                preprocessing_num_workers=1,
                max_samples=None,
            )
            attr_first = DatasetAttr(load_from="file", dataset_name="single.json")
            attr_first.split = "train"
            first_dataset = _load_single_dataset(attr_first, self.model_args, data_args_first, self.training_args)
            self.assertEqual(len(first_dataset), 3)

            # Invocation 2: directory path, sampling expansion, then truncation.
            data_args_second = SimpleNamespace(
                dataset_dir=self.data_dir,
                streaming=False,
                preprocessing_num_workers=1,
                max_samples=4,
            )
            attr_second = DatasetAttr(load_from="file", dataset_name="sample_dir")
            attr_second.split = "train"
            attr_second.num_samples = 5
            second_dataset = _load_single_dataset(attr_second, self.model_args, data_args_second, self.training_args)
            self.assertEqual(len(second_dataset), 4)

            # Invocation 3: file path with streaming conversion for local files.
            data_args_third = SimpleNamespace(
                dataset_dir=self.data_dir,
                streaming=True,
                preprocessing_num_workers=1,
                max_samples=None,
            )
            attr_third = DatasetAttr(load_from="file", dataset_name="single.json")
            attr_third.split = "train"
            third_dataset = _load_single_dataset(attr_third, self.model_args, data_args_third, self.training_args)
            self.assertTrue(third_dataset.is_iterable)

        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call["path"] == "json" for call in calls))
