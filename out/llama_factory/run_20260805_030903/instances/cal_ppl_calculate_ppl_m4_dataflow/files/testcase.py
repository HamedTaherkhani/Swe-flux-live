from __future__ import annotations

import json
import random
import runpy
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fire
import torch
import tqdm
import transformers
import llamafactory.data
import llamafactory.hparams
import llamafactory.model


class _Batch(dict):
    def to(self, device):
        return self


@dataclass
class _Collator:
    template: object = None
    tokenizer: object = None
    label_pad_token_id: int = -100
    mlm: bool = False

    def __call__(self, features):
        return features


class _Loader:
    def __init__(self, dataset, *args, **kwargs):
        self.dataset = dataset

    def __iter__(self):
        return iter(self.dataset)


class _Model:
    device = torch.device("cpu")

    def __call__(self, **batch):
        token_ids = batch["input_ids"]
        vocabulary = 19
        classes = torch.arange(vocabulary, dtype=torch.float32)
        centers = (token_ids * 3 + torch.arange(token_ids.shape[1])) % vocabulary
        logits = -((classes.view(1, 1, -1) - centers.unsqueeze(-1)).abs() / 2.5)
        return {"logits": logits}


def _make_dataset(stage):
    stage_code = sum(ord(char) for char in stage)
    rng = random.Random(8_731 + stage_code)
    batches = []
    for index in range(17):
        rows = 2 + ((index + stage_code) % 3)
        width = 6 + ((index * 5 + stage_code) % 4)
        values = torch.tensor(
            [[rng.randrange(19) for _ in range(width)] for _ in range(rows)],
            dtype=torch.long,
        )
        labels = (values * 7 + index + stage_code) % 19
        for row in range(rows):
            masked_column = (row * 3 + index + stage_code) % width
            labels[row, masked_column] = -100
        batches.append(_Batch(input_ids=values, labels=labels))
    return batches


class TestCalPplRuntime(unittest.TestCase):
    def test_cli_drives_all_training_stages(self):
        generated = []

        def fake_train_args(options):
            model_args = SimpleNamespace(source=options["model_name_or_path"])
            data_args = SimpleNamespace(stage=options["stage"])
            training_args = SimpleNamespace(enabled=options["do_train"])
            finetuning_args = SimpleNamespace(stage=options["stage"])
            return model_args, data_args, training_args, finetuning_args, None

        def fake_dataset(template, model_args, data_args, training_args, stage, **kwargs):
            return {"train_dataset": _make_dataset(stage)}

        def fake_fire(entrypoint):
            with tempfile.TemporaryDirectory() as directory:
                for ordinal, stage in enumerate(("pt", "sft", "rm")):
                    destination = Path(directory) / f"result-{ordinal}.json"
                    entrypoint(
                        model_name_or_path=f"synthetic-{ordinal}",
                        save_name=str(destination),
                        batch_size=2 + ordinal,
                        stage=stage,
                        dataset=f"generated-{ordinal}",
                        cutoff_len=64 + ordinal,
                        max_samples=51,
                        train_on_prompt=bool(ordinal % 2),
                    )
                    payload = json.loads(destination.read_text(encoding="utf-8"))
                    self.assertGreater(len(payload), len(stage))
                    self.assertTrue(all(value > 0 for value in payload))
                    generated.append(payload)

        patches = (
            patch.object(fire, "Fire", fake_fire),
            patch.object(torch.utils.data, "DataLoader", _Loader),
            patch.object(tqdm, "tqdm", lambda iterable, **kwargs: iterable),
            patch.object(transformers, "DataCollatorForLanguageModeling", _Collator),
            patch.object(llamafactory.data, "MultiModalDataCollatorForSeq2Seq", _Collator),
            patch.object(llamafactory.data, "get_dataset", fake_dataset),
            patch.object(llamafactory.data, "get_template_and_fix_tokenizer", lambda tokenizer, data_args: data_args),
            patch.object(llamafactory.hparams, "get_train_args", fake_train_args),
            patch.object(llamafactory.model, "load_tokenizer", lambda model_args: {"tokenizer": object()}),
            patch.object(llamafactory.model, "load_model", lambda *args, **kwargs: _Model()),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            runpy.run_module("scripts.stat_utils.cal_ppl", run_name="__main__")

        self.assertEqual(len(generated), len({id(item) for item in generated}))
