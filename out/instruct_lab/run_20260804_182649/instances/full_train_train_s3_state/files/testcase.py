import importlib
import os
import random
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np
import torch


class _Payload:
    def __init__(self, values):
        self.values = tuple(values)

    def __len__(self):
        return len(self.values)

    def to(self, device):
        self.device = str(device)
        return self


class _Metric:
    def __init__(self, value):
        self.value = float(value)

    def item(self):
        return self.value

    def __truediv__(self, divisor):
        return _Metric(self.value / float(divisor))

    def backward(self):
        self.backward_called = True

    def __repr__(self):
        return f"Metric({self.value:.6f})"


class _Vector:
    def __init__(self, size):
        self.values = [0.0] * size

    def __setitem__(self, index, value):
        self.values[index] = float(value)

    def __getitem__(self, index):
        return self.values[index]

    def to(self, device):
        self.device = str(device)
        return self

    def __repr__(self):
        values = ", ".join(f"{value:.6f}" for value in self.values)
        return f"Vector([{values}])"


class _Dataset:
    def __init__(self, lengths, salts):
        self.lengths = np.array(lengths, dtype=np.int64)
        self.salts = tuple(salts)

    def get_lengths(self):
        return self.lengths

    def __len__(self):
        return len(self.lengths)


class _Sampler:
    def __init__(self, lengths, seed, **_kwargs):
        self.lengths = tuple(int(value) for value in lengths)
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch):
        self.epoch = epoch


class _DataLoader:
    def __init__(self, dataset, batch_sampler, **_kwargs):
        self.dataset = dataset
        self.batch_sampler = batch_sampler
        self.multiprocessing_context = None

    def __len__(self):
        return len(self.dataset)

    def __iter__(self):
        for index, (width, salt) in enumerate(
            zip(self.dataset.lengths, self.dataset.salts)
        ):
            epoch = self.batch_sampler.epoch
            values = [
                (salt + (position + 3) * (index + 5) + epoch * (position + 7))
                % 101
                for position in range(int(width))
            ]
            labels = [
                value if (value + index + epoch) % 5 else -100 for value in values
            ]
            counted = 1 + sum(value != -100 for value in labels)
            yield {
                "input_ids": _Payload(values),
                "labels": _Payload(labels),
                "attention_mask": _Payload(
                    (value + index + epoch) % 2 for value in values
                ),
                "num_loss_counted_tokens": counted,
            }


class _Config:
    vocab_size = 23
    pad_token_id = 3
    bos_token_id = 5
    eos_token_id = 7

    def to_json_file(self, path):
        Path(path).write_text("{}\n", encoding="utf-8")


class _Model:
    def __init__(self):
        self.config = _Config()
        self.calls = 0
        self.backward_inputs = []

    def resize_token_embeddings(self, size):
        self.config.vocab_size = size

    def to(self, device):
        self.device = str(device)
        return self

    def parameters(self):
        return iter([SimpleNamespace(name="parameter")])

    def gradient_checkpointing_enable(self):
        self.checkpointing = True

    def train(self):
        self.training = True

    def __call__(self, input_ids, labels, attention_mask, **_kwargs):
        self.calls += 1
        weighted = sum(
            (position + 1) * value
            for position, value in enumerate(input_ids.values)
        )
        label_mass = sum(value for value in labels.values if value != -100)
        mask_mass = sum(attention_mask.values)
        return SimpleNamespace(
            loss=_Metric(
                (weighted * 7 + label_mass * 3 + mask_mass * 11 + self.calls**2)
                / (19 + len(input_ids))
            )
        )

    def state_dict(self):
        return {"calls": self.calls, "vocab_size": self.config.vocab_size}


class _Tokenizer:
    pad_token_id = 13
    bos_token_id = 17
    eos_token_id = 19

    def __len__(self):
        return 61

    def save_pretrained(self, path):
        Path(path, "tokenizer.json").write_text("{}\n", encoding="utf-8")


class _Optimizer:
    def __init__(self, _parameters, **_kwargs):
        self.steps = 0
        self.clears = 0

    def step(self):
        self.steps += 1

    def zero_grad(self):
        self.clears += 1


class _Progress:
    def __init__(self, values, **_kwargs):
        self.values = tuple(values)
        self.updates = 0

    def update(self, amount):
        self.updates += amount


class TestFullPipeline(unittest.TestCase):
    def test_seeded_batches(self):
        rng = random.Random(681_947)
        lengths = [
            8 + ((index * index + rng.randrange(97)) % 17) for index in range(19)
        ]
        salts = [
            (rng.randrange(10_000) + length * (index + 11)) % 997
            for index, length in enumerate(lengths)
        ]
        dataset = _Dataset(lengths, salts)
        model = _Model()
        tokenizer = _Tokenizer()

        config_module = ModuleType("instructlab.training.config")
        config_module.DataProcessArgs = lambda **kwargs: SimpleNamespace(**kwargs)
        process_module = ModuleType("instructlab.training.data_process")
        process_module.main = lambda _args: None
        sampler_module = ModuleType("instructlab.training.multipack_sampler")

        def packing_details(**kwargs):
            observed = tuple(int(value) for value in kwargs["dataset"].get_lengths())
            return max(observed) + sum(observed) % 9, 4 + sum(observed) % 4

        sampler_module.find_packing_max_batch_len_and_grad_accum = packing_details
        sampler_module.MultipackDistributedBatchSampler = _Sampler
        dataset_module = ModuleType("instructlab.training.token_dataset")
        dataset_module.setup_dataset = lambda _path: dataset
        tokenizer_module = ModuleType("instructlab.training.tokenizer_utils")
        tokenizer_module.setup_tokenizer = lambda *_args: tokenizer
        utils_module = ModuleType("instructlab.training.utils")
        utils_module.retrieve_chat_template = lambda _path: ("template", ("tokens",))
        utils_module.convert_loss_to_reduce_sum = lambda value: value
        utils_module.add_noisy_embeddings = lambda value, noise_alpha: value

        fake_modules = {
            module.__name__: module
            for module in (
                config_module,
                process_module,
                sampler_module,
                dataset_module,
                tokenizer_module,
                utils_module,
            )
        }

        cli_module = importlib.import_module("instructlab.cli.model." + "train")
        implementation = importlib.import_module(
            "instructlab.model." + "full_" + "train"
        )
        callback = cli_module.train.callback
        while hasattr(callback, "__wrapped__"):
            callback = callback.__wrapped__

        with tempfile.TemporaryDirectory() as workdir:
            data_path = Path(workdir, "generated.jsonl")
            data_path.write_text("{}\n", encoding="utf-8")
            args = SimpleNamespace(
                data_output_dir=str(Path(workdir, "processed")),
                model_path=str(Path(workdir, "model")),
                data_path=str(data_path),
                max_seq_len=max(lengths) * 3,
                chat_tmpl_path=str(Path(workdir, "chat-template")),
                effective_batch_size=sum(lengths) % 23 + 9,
                max_batch_len=max(lengths) * 5,
                num_epochs=2,
                ckpt_output_dir=str(Path(workdir, "checkpoints")),
            )

            data_loader_module = importlib.import_module("torch.utils.data")
            with (
                patch.dict(sys.modules, fake_modules),
                patch.object(data_loader_module, "DataLoader", _DataLoader),
                patch.object(torch, "zeros", lambda size, **_kwargs: _Vector(size)),
                patch.object(cli_module, "map_train_to_library", return_value=(args, None)),
                patch.object(implementation, "Adafactor", _Optimizer),
                patch.object(
                    implementation.AutoConfig,
                    "from_pretrained",
                    return_value=_Config(),
                ),
                patch.object(
                    implementation.AutoModelForCausalLM,
                    "from_pretrained",
                    return_value=model,
                ),
                patch.object(implementation, "tqdm", _Progress),
                patch.object(
                    implementation.psutil,
                    "virtual_memory",
                    return_value=SimpleNamespace(total=(73 + sum(lengths) % 31) * 1024**3),
                ),
                patch.object(
                    implementation,
                    "llamacpp_convert_to_gguf",
                    SimpleNamespace(convert_llama_to_gguf=lambda **_kwargs: None),
                ),
                patch.object(implementation, "run_quantize", lambda *_args: None),
                patch.object(
                    implementation,
                    "is_macos_with_m_chip",
                    return_value=False,
                ),
            ):
                callback(
                    ctx=SimpleNamespace(
                        obj=SimpleNamespace(
                            config=SimpleNamespace(
                                generate=SimpleNamespace(output_dir=workdir)
                            )
                        ),
                        params={},
                        fail=lambda message: self.fail(message),
                    ),
                    data_path=str(data_path),
                    input_dir=workdir,
                    skip_preprocessing=False,
                    tokenizer_dir=None,
                    gguf_model_path=None,
                    model_path=args.model_path,
                    iters=0,
                    local=True,
                    skip_quantize=False,
                    num_epochs=args.num_epochs,
                    device="cpu",
                    four_bit_quant=False,
                    strategy=None,
                    phased_base_dir=None,
                    phased_phase1_data=None,
                    phased_phase1_num_epochs=None,
                    phased_phase1_samples_per_save=None,
                    phased_phase1_learning_rate=None,
                    phased_phase1_effective_batch_size=None,
                    phased_phase2_data=None,
                    phased_phase2_num_epochs=None,
                    phased_phase2_samples_per_save=None,
                    phased_phase2_learning_rate=None,
                    phased_phase2_effective_batch_size=None,
                    phased_mt_bench_judge=None,
                    skip_user_confirm=True,
                    enable_serving_output=False,
                    pipeline="full",
                    training_journal=None,
                    force_clear_phased_cache=False,
                    distributed_backend=None,
                    optimize_memory=False,
                    disable_accelerate_full_state_at_epoch=False,
                )

        self.assertGreater(model.calls, len(lengths))
        self.assertTrue(model.training)
        self.assertGreater(model.config.vocab_size, len(tokenizer))
