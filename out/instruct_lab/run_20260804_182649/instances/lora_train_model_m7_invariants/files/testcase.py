import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


class GeneratedTokenizer:
    eos_token_id = -1

    def encode(self, text):
        salt = sum((index + 5) * ord(char) for index, char in enumerate(text))
        width = 9 + salt % 23
        return [
            2 + (salt + index * index * 7 + index * 13) % 101
            for index in range(width)
        ]


class GeneratedModel:
    def __init__(self):
        self.model = types.SimpleNamespace(layers=[])
        self.update_marks = []

    def freeze(self):
        return None

    def parameters(self):
        width = sum((index * 11 + 7) % 19 for index in range(29))
        return {"weights": np.arange(width, dtype=np.float32)}

    def trainable_parameters(self):
        width = sum((index * index + 3) % 17 for index in range(31))
        return {"adapter": np.arange(width, dtype=np.float32)}


def install_generated_modules(created_models, created_optimizers):
    mlx = types.ModuleType("mlx")
    core = types.ModuleType("mlx.core")
    nn = types.ModuleType("mlx.nn")
    optimizers = types.ModuleType("mlx.optimizers")
    mlx_utils = types.ModuleType("mlx.utils")

    core.array = np.array
    core.float32 = np.float32
    core.eval = lambda *unused: None
    core.savez = lambda unused_path, **unused_values: None
    mlx.core = core
    mlx.nn = nn
    mlx.optimizers = optimizers
    mlx_utils.tree_flatten = lambda mapping: sorted(mapping.items())

    def value_and_grad(unused_model, unused_loss):
        def generated_step(model, inputs, targets, lengths):
            weighted_lengths = sum(
                (index + 3) * int(value) for index, value in enumerate(lengths)
            )
            edge_signal = int(np.sum(inputs[:, 0]) + np.sum(targets[:, -1]))
            token_count = np.int64(
                int(np.sum(lengths)) + (weighted_lengths + edge_signal) % 19
            )
            loss_value = np.float64(
                ((weighted_lengths * 7 + edge_signal * 11) % 1009) / 97.0
            )
            gradient = {
                "signal": np.array(
                    [weighted_lengths % 31, edge_signal % 37], dtype=np.float32
                )
            }
            model.update_marks.append((weighted_lengths, edge_signal))
            return (loss_value, token_count), gradient

        return generated_step

    nn.value_and_grad = value_and_grad

    class GeneratedAdam:
        def __init__(self, learning_rate):
            self.learning_rate = learning_rate
            self.state = {"updates": 0}
            self.update_count = 0
            created_optimizers.append(self)

        def update(self, unused_model, gradient):
            self.update_count += 1
            self.state["updates"] = self.update_count + int(
                np.sum(gradient["signal"])
            )

    optimizers.Adam = GeneratedAdam

    generated_utils = types.ModuleType("instructlab.train.lora_mlx.utils")
    tokenizer = GeneratedTokenizer()

    def load_generated(unused_path):
        model = GeneratedModel()
        created_models.append(model)
        return model, tokenizer, {}

    generated_utils.load = load_generated
    generated_utils.generate = lambda *unused: iter(())

    generated_lora_model = types.ModuleType(
        "instructlab.train.lora_mlx.models.lora"
    )
    generated_lora_model.LoRALinear = type(
        "GeneratedLoRALinear",
        (),
        {"from_linear": staticmethod(lambda linear: linear)},
    )

    return {
        "mlx": mlx,
        "mlx.core": core,
        "mlx.nn": nn,
        "mlx.optimizers": optimizers,
        "mlx.utils": mlx_utils,
        "instructlab.train.lora_mlx.utils": generated_utils,
        "instructlab.train.lora_mlx.models.lora": generated_lora_model,
    }


class TestGeneratedLoraTraining(unittest.TestCase):
    def test_seeded_training_state(self):
        seed_text = "runtime-state-through-caller"
        seed = sum((index + 1) * ord(char) for index, char in enumerate(seed_text))

        def generated_records(count, phase):
            return [
                {
                    "text": "".join(
                        chr(
                            97
                            + (
                                seed
                                + phase * 17
                                + row * 11
                                + column * column * 5
                            )
                            % 26
                        )
                        for column in range(14 + (row * row + phase * 3) % 29)
                    )
                }
                for row in range(count)
            ]

        train_records = generated_records(
            sum(1 for index in range(79) if (index * index + seed) % 7 != 0), 3
        )
        valid_records = generated_records(
            sum(1 for index in range(37) if (index * 5 + seed) % 6 != 1), 5
        )
        test_records = generated_records(
            sum(1 for index in range(23) if (index * 7 + seed) % 9 != 2), 7
        )
        iteration_budget = sum(
            1
            for index in range(43 + seed % 23)
            if (index * index * 3 + seed) % 8 != 0
        )

        created_models = []
        created_optimizers = []
        modules = install_generated_modules(created_models, created_optimizers)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "generated-data"
            data_dir.mkdir()
            for name, records in (
                ("train", train_records),
                ("valid", valid_records),
                ("test", test_records),
            ):
                with (data_dir / f"{name}.jsonl").open(
                    "w", encoding="utf-8"
                ) as stream:
                    for record in records:
                        stream.write(json.dumps(record, sort_keys=True) + "\n")

            with mock.patch.dict(sys.modules, modules):
                module = importlib.import_module("instructlab.train.lora_mlx.lora")
                def generated_evaluation(
                    model, dataset, unused_loss, unused_tokenizer, batch_size, num_batches
                ):
                    update_signal = sum(
                        left * 3 + right * 5 for left, right in model.update_marks[-7:]
                    )
                    return (
                        update_signal + len(dataset) * batch_size + num_batches
                    ) / (len(dataset) + num_batches)

                with mock.patch.object(
                    module, "evaluate", side_effect=generated_evaluation
                ):
                    module.load_and_train(
                        model=str(Path(temp_dir) / "generated-model"),
                        train=True,
                        data=str(data_dir),
                        batch_size=3 + seed % 3,
                        iters=iteration_budget,
                        val_batches=2 + seed % 4,
                        learning_rate=(1 + seed % 13) / 10000,
                        steps_per_report=5 + seed % 5,
                        steps_per_eval=9 + seed % 7,
                        adapter_file=str(Path(temp_dir) / "generated-adapter.npz"),
                        save_every=iteration_budget + len(valid_records),
                        no_adapter=True,
                        seed=seed % 97,
                    )

        self.assertEqual(len(created_models), 1)
        self.assertEqual(len(created_optimizers), 1)
        self.assertGreater(
            created_optimizers[0].update_count,
            len(test_records),
        )
        self.assertEqual(
            len(created_models[0].update_marks),
            created_optimizers[0].update_count,
        )
