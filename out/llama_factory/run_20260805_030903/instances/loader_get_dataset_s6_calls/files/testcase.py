import random
import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import llamafactory.data.loader as loader_module
import llamafactory.train.test_utils as train_test_utils


class _MemoryDataset:
    def __init__(self, rows, label):
        self.rows = list(rows)
        self.label = label

    def __iter__(self):
        return iter(self.rows)

    def map(self, transform, batched, batch_size, remove_columns, **kwargs):
        stride = max(1, batch_size % 7)
        transformed = []
        for offset in range(0, len(self.rows), stride):
            batch = self.rows[offset : offset + stride]
            transformed.extend(transform(batch))
        return _MemoryDataset(transformed, f"{self.label}:mapped:{len(remove_columns)}:{len(kwargs)}")


class _ProcessorHarness:
    def __init__(self, template, tokenizer, processor, data_args):
        self.bias = (len(template.tag) + tokenizer.vocab_span + data_args.preprocessing_batch_size) % 17

    def preprocess_dataset(self, batch):
        return [
            {
                "input_ids": [
                    (row["token"] * (position + 3) + self.bias) % 211
                    for position in range(5 + row["token"] % 6)
                ]
            }
            for row in batch
            if (row["token"] + self.bias) % 9 != 0
        ]


class TestIndirectDatasetModuleCallGraph(unittest.TestCase):
    def test_seeded_multi_stage_dataset_modules(self):
        seed_material = sum((index + 11) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed_material)
        stages = ["pt", "sft", "rm", "kto", "ppo", "sft"]
        rng.shuffle(stages)
        markers = [(rng.randrange(10_000, 90_000) ^ (index * 7919)) for index in range(len(stages))]
        state = {"invocation": 0, "stage": None, "map_calls": 0}

        def fake_get_train_args(kwargs):
            ordinal = state["invocation"]
            stage = kwargs["stage"]
            marker = kwargs["marker"]
            state["invocation"] += 1
            state["stage"] = stage

            train_count = 18 + ((marker // 7 + ordinal * ordinal) % 8)
            eval_count = 17 + ((marker // 13 + ordinal * 5) % 11)
            train_names = [f"train-{ordinal}-{index}-{(marker * (index + 5)) % 100_003}" for index in range(train_count)]
            eval_names = [f"eval-{ordinal}-{index}-{(marker + index * index * 37) % 100_019}" for index in range(eval_count)]
            rng.shuffle(train_names)
            rng.shuffle(eval_names)

            data_args = SimpleNamespace(
                tokenized_path=None,
                dataset=train_names,
                eval_dataset=eval_names,
                dataset_dir="generated/in-memory",
                streaming=False,
                preprocessing_num_workers=None,
                overwrite_cache=bool((marker + ordinal) % 2),
                preprocessing_batch_size=19 + marker % 23,
                packing=bool((marker // 3) % 2),
                neat_packing=False,
            )
            training_args = SimpleNamespace(
                do_predict=False,
                predict_with_generate=bool((marker // 5) % 2),
                local_process_index=ordinal % 3,
                should_log=False,
                should_save=False,
                seed=(marker * 31 + ordinal) % 1_000_003,
                main_process_first=lambda **_kwargs: nullcontext(),
            )
            return SimpleNamespace(), data_args, training_args, SimpleNamespace(), SimpleNamespace()

        def fake_dataset_list(names, _dataset_dir):
            ranking = state["stage"] == "rm"
            return [
                SimpleNamespace(dataset_name=name, ranking=ranking, load_from="memory")
                for name in names
            ]

        def fake_load(dataset_attr, _model_args, _data_args, training_args):
            checksum = sum((index + 1) * ord(char) for index, char in enumerate(dataset_attr.dataset_name))
            row_count = 16 + (checksum + training_args.seed) % 13
            rows = [
                {"token": (checksum * (index + 7) + training_args.seed) % 997, "source": dataset_attr.dataset_name}
                for index in range(row_count)
            ]
            return _MemoryDataset(rows, dataset_attr.dataset_name)

        def fake_merge(datasets, _data_args, seed):
            ordered = sorted(datasets, key=lambda dataset: (len(dataset.rows) + seed) % 29)
            rows = [row for dataset in ordered for row in dataset.rows]
            return _MemoryDataset(rows, f"merged:{len(ordered)}")

        original_map = _MemoryDataset.map

        def counted_map(dataset, *args, **kwargs):
            state["map_calls"] += 1
            return original_map(dataset, *args, **kwargs)

        def fake_split(train, evaluation, _data_args, seed):
            return {
                "train_dataset": train,
                "eval_dataset": evaluation,
                "seed_parity": seed % 2,
            }

        processor_names = [
            "PretrainDatasetProcessor",
            "PackedSupervisedDatasetProcessor",
            "SupervisedDatasetProcessor",
            "PairwiseDatasetProcessor",
            "FeedbackDatasetProcessor",
            "UnsupervisedDatasetProcessor",
        ]
        patches = [
            patch.object(train_test_utils, "get_train_args", side_effect=fake_get_train_args),
            patch.object(train_test_utils, "load_tokenizer", return_value={"tokenizer": SimpleNamespace(vocab_span=127)}),
            patch.object(
                train_test_utils,
                "get_template_and_fix_tokenizer",
                side_effect=lambda _tokenizer, data_args: SimpleNamespace(
                    tag=f"template:{data_args.preprocessing_batch_size}"
                ),
            ),
            patch.object(loader_module, "get_dataset_list", side_effect=fake_dataset_list),
            patch.object(loader_module, "_load_single_dataset", side_effect=fake_load),
            patch.object(loader_module, "merge_dataset", side_effect=fake_merge),
            patch.object(loader_module, "split_dataset", side_effect=fake_split),
            patch.object(loader_module, "get_dataset_module", side_effect=lambda value: value),
            patch.object(_MemoryDataset, "map", new=counted_map),
        ]
        patches.extend(patch.object(loader_module, name, _ProcessorHarness) for name in processor_names)
        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            results = [
                train_test_utils.load_dataset_module(stage=stage, marker=marker)
                for stage, marker in zip(stages, markers)
            ]

        self.assertEqual(state["invocation"], len(stages))
        self.assertTrue(all(set(result) == {"train_dataset", "eval_dataset", "seed_parity"} for result in results))
        self.assertTrue(all(isinstance(result["eval_dataset"], dict) for result in results))
        self.assertGreater(state["map_calls"], sum(len(result["eval_dataset"]) for result in results))
