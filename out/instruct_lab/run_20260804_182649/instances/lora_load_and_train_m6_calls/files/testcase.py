import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from click.testing import CliRunner

from instructlab.model import test as model_test


class GeneratedTokenizer:
    eos_token_id = -1

    def encode(self, text):
        return [((ord(char) * (index + 3)) % 89) + 2 for index, char in enumerate(text)]

    def decode(self, tokens):
        return "".join(chr(97 + (int(token) % 26)) for token in tokens)


class GeneratedModel:
    def __init__(self):
        self.model = types.SimpleNamespace(layers=[])

    def freeze(self):
        return None

    def parameters(self):
        width = sum((index * index + 5) % 17 for index in range(31))
        return {"weights": np.zeros(width, dtype=np.float32)}

    def trainable_parameters(self):
        width = sum((index * 7 + 3) % 13 for index in range(23))
        return {"adapter": np.zeros(width, dtype=np.float32)}


def install_generated_mlx_modules():
    mlx = types.ModuleType("mlx")
    core = types.ModuleType("mlx.core")
    nn = types.ModuleType("mlx.nn")
    optimizers = types.ModuleType("mlx.optimizers")
    mlx_utils = types.ModuleType("mlx.utils")

    core.array = np.array
    core.float32 = np.float32
    mlx.core = core
    mlx.nn = nn
    mlx.optimizers = optimizers
    mlx_utils.tree_flatten = lambda mapping: sorted(mapping.items())

    generated_utils = types.ModuleType("instructlab.train.lora_mlx.utils")
    tokenizer = GeneratedTokenizer()
    generated_utils.load = lambda unused: (GeneratedModel(), tokenizer, {})

    def token_stream(prompt, unused_model, unused_temp):
        span = sum((int(value) * (index + 1)) % 37 for index, value in enumerate(prompt))
        for index in range(17 + span % 19):
            yield np.int64((span + index * index + index * 11) % 71)

    generated_utils.generate = token_stream

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


class TestLoraPublicModelCommand(unittest.TestCase):
    def test_generated_prompt_batch(self):
        example_count = sum(1 for index in range(47) if (index * index + 3) % 5)
        examples = [
            {
                "system": f"policy-{(index * 13 + 7) % 29}",
                "user": "".join(
                    chr(97 + ((index * 11 + offset * offset) % 26))
                    for offset in range(19 + index % 13)
                ),
                "assistant": f"expected-{(index**3 + 17) % 101}",
            }
            for index in range(example_count)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "generated-data"
            model_dir = root / "generated-model"
            data_dir.mkdir()
            model_dir.mkdir()
            with (data_dir / "test.jsonl").open("w", encoding="utf-8") as stream:
                for example in examples:
                    stream.write(json.dumps(example, sort_keys=True) + "\n")

            modules = install_generated_mlx_modules()
            runner = CliRunner()
            with (
                mock.patch.dict(sys.modules, modules),
                mock.patch.object(
                    model_test.utils, "is_macos_with_m_chip", return_value=True
                ),
                mock.patch.object(
                    model_test.utils, "get_model_arch", return_value="generated"
                ),
                mock.patch.object(
                    model_test.utils,
                    "get_sysprompt",
                    side_effect=lambda arch: f"system-for-{arch}",
                ),
            ):
                result = runner.invoke(
                    model_test.test,
                    [
                        "--data-dir",
                        str(data_dir),
                        "--model-dir",
                        str(model_dir),
                        "--adapter-file",
                        "none",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(result.output.rstrip().endswith("ᕦ(òᴗóˇ)ᕤ"))
        self.assertEqual(result.output.count("model output BEFORE"), len(examples))
