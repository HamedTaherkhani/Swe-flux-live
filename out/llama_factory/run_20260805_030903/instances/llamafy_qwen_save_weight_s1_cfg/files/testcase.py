import json
import random
import tempfile
import unittest
from pathlib import Path

import torch
from safetensors.torch import save_file

from scripts.convert_ckpt import llamafy_qwen as converter


class TestQwenConversionControlFlow(unittest.TestCase):
    def test_three_generated_checkpoint_conversions(self):
        rng = random.Random(sum(ord(character) for character in self.id()))

        def make_checkpoint(directory: Path, layer_count: int) -> None:
            directory.mkdir()
            tensors = {}
            width = 4
            for layer in range(layer_count):
                prefix = f"transformer.h.{layer}"
                offset = rng.randrange(1, 9)
                tensors[f"{prefix}.attn.c_attn.weight"] = (
                    torch.arange(3 * width * width, dtype=torch.float32).reshape(3 * width, width) + offset
                )
                tensors[f"{prefix}.attn.c_proj.weight"] = (
                    torch.arange(width * width, dtype=torch.float32).reshape(width, width) + offset
                )
                for suffix in ("ln_1.weight", "ln_2.weight"):
                    tensors[f"{prefix}.{suffix}"] = torch.arange(width, dtype=torch.float32) + offset
                for suffix in ("mlp.w1.weight", "mlp.w2.weight", "mlp.c_proj.weight"):
                    tensors[f"{prefix}.{suffix}"] = (
                        torch.arange(width * width, dtype=torch.float32).reshape(width, width) + offset
                    )

            tensors["transformer.wte.weight"] = torch.arange(width * width, dtype=torch.float32).reshape(
                width, width
            )
            tensors["transformer.ln_f.weight"] = torch.arange(width, dtype=torch.float32)
            tensors["lm_head.weight"] = torch.arange(width * width, dtype=torch.float32).reshape(width, width)
            save_file(tensors, directory / "generated.safetensors")

            config = {
                "hidden_size": width,
                "initializer_range": rng.random() / width,
                "intermediate_size": width * width,
                "max_position_embeddings": width**width,
                "num_attention_heads": width,
                "num_hidden_layers": layer_count,
                "kv_channels": 1,
                "layer_norm_epsilon": rng.random() / (width**width),
                "tie_word_embeddings": bool(layer_count % 2),
                "vocab_size": width**3,
            }
            (directory / converter.CONFIG_NAME).write_text(json.dumps(config), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scenarios = (
                (sum((2, 2)), str(8) + "GB", False),
                (sum((3, 3)), str(1) + "KB", True),
                (sum((2, 3)), str(2) + "KB", False),
            )

            for index, (layers, shard_size, use_safe_format) in enumerate(scenarios):
                input_dir = root / f"input-{index}"
                output_dir = root / f"output-{index}"
                make_checkpoint(input_dir, layers)
                converter.llamafy_qwen(
                    input_dir=str(input_dir),
                    output_dir=str(output_dir),
                    shard_size=shard_size,
                    save_safetensors=use_safe_format,
                )

            generated_configs = sorted(root.glob("output-*/config.json"))
            self.assertEqual(len(generated_configs), len(scenarios))
            self.assertTrue(all(json.loads(path.read_text())["torch_dtype"] == "float32" for path in generated_configs))
            self.assertGreater(sum(1 for path in root.glob("output-*/*") if path.name != "config.json"), len(scenarios))
