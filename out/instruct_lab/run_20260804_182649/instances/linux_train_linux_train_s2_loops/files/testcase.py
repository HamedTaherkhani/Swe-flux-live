import importlib
import os
import random
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import torch

from instructlab.model import simple_train


class _Tensor:
    def squeeze(self):
        return self

    def to(self, _device):
        return self


class _Tokenized(dict):
    def __init__(self):
        super().__init__(input_ids=_Tensor())
        self.input_ids = self["input_ids"]


class _Tokenizer:
    eos_token = "<eos>"
    eos_token_id = 71
    pad_token = None
    padding_side = "left"
    decode_calls = 0

    def encode(self, text, add_special_tokens=False):
        return [len(text) % 13, int(add_special_tokens), 5, 8, 13, 21]

    def __call__(self, text, **_kwargs):
        self.last_text_size = len(text)
        return _Tokenized()

    def batch_decode(self, outputs):
        type(self).decode_calls += 1
        checksum = sum(sum(sequence) for sequence in outputs)
        return [f"prefix <|assistant|> generated-{checksum}-{type(self).decode_calls}"]


class _Dataset:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def to_pandas(self):
        return SimpleNamespace(head=lambda: self._rows[:5])


class _AttentionProjection:
    def __init__(self, seed):
        self.seed = seed
        self.yielded = 0

    def named_parameters(self):
        rng = random.Random(self.seed)
        for position in range(53):
            score = (rng.randrange(10_000) + position * position + 17 * position) % 19
            if score not in {0, 4, 7, 11, 18}:
                self.yielded += 1
                stem = chr(97 + (score + position) % 26)
                name = (
                    f"{stem}.projection_{position}_{score}"
                    if (score * position) % 3
                    else f"bias_{stem}_{position}"
                )
                yield name, SimpleNamespace(position=position)


class _Model:
    def __init__(self, attention):
        self.device = torch.device("cpu")
        self.config = SimpleNamespace(use_cache=False)
        self._attention = attention
        self.generated = 0

    def to(self, device):
        self.device = device
        return self

    def modules(self):
        return iter([SimpleNamespace(), self._attention, SimpleNamespace()])

    def generate(self, **_kwargs):
        self.generated += 1
        width = 5 + self.generated % 7
        return [[(self.generated * factor + width) % 97 for factor in range(1, width)]]

    def merge_and_unload(self):
        return self

    def save_pretrained(self, path):
        Path(path).mkdir(parents=True)


class _Trainer:
    train_calls = 0

    def __init__(self, model, **_kwargs):
        self.model = model

    def train(self):
        type(self).train_calls += 1


class TestLinuxTrainingLoop(unittest.TestCase):
    def test_generated_attention_parameters(self):
        rng = random.Random(942_731)
        row_count = 21 + rng.randrange(9)
        rows = []
        for row in range(row_count):
            width = 9 + (row * row + rng.randrange(17)) % 14
            user = "".join(chr(97 + rng.randrange(26)) for _ in range(width))
            expected = "".join(reversed(user[:: 1 + row % 5]))
            rows.append(
                {
                    "system": f"policy-{sum(map(ord, user)) % 29}",
                    "user": user,
                    "assistant": expected,
                }
            )

        train_rows = rows + [
            {
                "system": item["system"],
                "user": item["user"][::-1],
                "assistant": item["assistant"],
            }
            for item in rows[::3]
        ]
        attention = _AttentionProjection(
            sum((index + 1) * ord(char) for index, char in enumerate(rows[4]["user"]))
        )
        model = _Model(attention)
        tokenizer = _Tokenizer()
        train_module = importlib.import_module(
            "instructlab.train." + "linux_" + "train"
        )

        def fake_load_dataset(_format, data_files, split):
            self.assertEqual(split, "train")
            selected = train_rows if Path(data_files).name.startswith("train") else rows
            return _Dataset(selected)

        _Tokenizer.decode_calls = 0
        _Trainer.train_calls = 0

        with tempfile.TemporaryDirectory() as workdir:
            previous_cwd = os.getcwd()
            os.chdir(workdir)
            try:
                checkpoint_parent = Path(workdir) / "caller-checkpoints"
                checkpoint_parent.mkdir()
                with (
                    patch.object(simple_train.utils, "is_macos_with_m_chip", return_value=False),
                    patch.object(
                        simple_train,
                        "DEFAULTS",
                        SimpleNamespace(
                            CHECKPOINTS_DIR=str(checkpoint_parent / "converted"),
                            DATASETS_DIR=str(Path(workdir) / "default-data"),
                        ),
                    ),
                    patch.object(train_module, "load_dataset", side_effect=fake_load_dataset),
                    patch.object(train_module, "ensure_legacy_dataset", side_effect=lambda value: value),
                    patch.object(
                        train_module.AutoTokenizer,
                        "from_pretrained",
                        return_value=tokenizer,
                    ),
                    patch.object(
                        train_module.AutoConfig,
                        "from_pretrained",
                        return_value=SimpleNamespace(),
                    ),
                    patch.object(
                        train_module.AutoModelForCausalLM,
                        "from_pretrained",
                        return_value=model,
                    ),
                    patch.object(
                        train_module,
                        "DataCollatorForCompletionOnlyLM",
                        side_effect=lambda *_args, **_kwargs: SimpleNamespace(),
                    ),
                    patch.object(
                        train_module,
                        "StoppingCriteriaList",
                        side_effect=lambda value: list(value),
                    ),
                    patch.object(
                        train_module,
                        "LoraConfig",
                        side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
                    ),
                    patch.object(
                        train_module,
                        "SFTConfig",
                        side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
                    ),
                    patch.object(train_module, "SFTTrainer", _Trainer),
                    patch.object(train_module, "tqdm", side_effect=lambda value: value),
                    patch.object(
                        train_module,
                        "CONTEXTS",
                        {"default": lambda _name: "deterministic system"},
                    ),
                ):
                    with self.assertRaises(StopIteration):
                        simple_train.simple_train(
                            model_path="synthetic/model",
                            skip_preprocessing=True,
                            skip_quantize=True,
                            gguf_model_path=None,
                            tokenizer_dir=None,
                            data_path=str(Path(workdir) / "prepared-data"),
                            input_dir=str(Path(workdir) / "unused-input"),
                            ckpt_output_dir=str(Path(workdir) / "checkpoints"),
                            iters=37,
                            local=True,
                            num_epochs=2,
                            device="cpu",
                            four_bit_quant=False,
                        )
            finally:
                os.chdir(previous_cwd)

        self.assertGreater(attention.yielded, 15)
        self.assertGreater(model.generated, len(rows))
        self.assertEqual(_Trainer.train_calls, 1)
