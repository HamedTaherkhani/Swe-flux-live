import unittest
from collections import OrderedDict
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.convert_ckpt import llamafy_qwen


class _FakeSafeOpen:
    def __init__(self, path, framework, device, per_file_tensors):
        self._path = path
        self._framework = framework
        self._device = device
        self._per_file_tensors = per_file_tensors

    def __enter__(self):
        self._mapping = self._per_file_tensors[self._path]
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def keys(self):
        return list(self._mapping.keys())

    def get_tensor(self, key):
        return self._mapping[key]


class TestLlamafyQwenSaveWeightM3State(unittest.TestCase):
    def test_conversion_loop_state_snapshots(self):
        with TemporaryDirectory() as input_dir, TemporaryDirectory() as output_dir:
            file1 = str(Path(input_dir) / "part1.safetensors")
            file2 = str(Path(input_dir) / "part2.safetensors")

            per_file_tensors = {
                file1: OrderedDict(
                    [
                        ("transformer.h.0.attn.c_attn.weight", torch.arange(12, dtype=torch.float32).reshape(6, 2)),
                        ("transformer.h.0.attn.c_proj.weight", torch.tensor([[1.0, 2.0], [3.0, 4.0]])),
                        ("transformer.h.0.ln_1.weight", torch.tensor([0.1, 0.2])),
                        ("transformer.h.0.ln_2.weight", torch.tensor([0.3, 0.4])),
                    ]
                ),
                file2: OrderedDict(
                    [
                        ("transformer.h.0.mlp.w1.weight", torch.tensor([[5.0, 6.0], [7.0, 8.0]])),
                        ("transformer.h.0.mlp.w2.weight", torch.tensor([[9.0, 10.0], [11.0, 12.0]])),
                        ("transformer.h.0.mlp.c_proj.weight", torch.tensor([[13.0, 14.0], [15.0, 16.0]])),
                        ("wte.weight", torch.tensor([[0.5, 0.6], [0.7, 0.8], [0.9, 1.0]])),
                        ("ln_f.weight", torch.tensor([1.1, 1.2])),
                        ("lm_head.weight", torch.tensor([[2.1, 2.2], [2.3, 2.4], [2.5, 2.6]])),
                    ]
                ),
            }

            split_result = SimpleNamespace(
                filename_to_tensors={
                    "pytorch_model-00001-of-00002.bin": [
                        "model.embed_tokens.weight",
                        "model.layers.0.self_attn.q_proj.weight",
                        "model.layers.0.self_attn.k_proj.weight",
                        "model.layers.0.self_attn.v_proj.weight",
                        "model.layers.0.self_attn.o_proj.weight",
                        "model.layers.0.self_attn.o_proj.bias",
                    ],
                    "pytorch_model-00002-of-00002.bin": [
                        "model.layers.0.input_layernorm.weight",
                        "model.layers.0.post_attention_layernorm.weight",
                        "model.layers.0.mlp.up_proj.weight",
                        "model.layers.0.mlp.gate_proj.weight",
                        "model.layers.0.mlp.down_proj.weight",
                        "model.norm.weight",
                        "lm_head.weight",
                    ],
                },
                is_sharded=True,
                metadata={"total_size": 1234},
                tensor_to_filename={
                    "model.embed_tokens.weight": "pytorch_model-00001-of-00002.bin",
                    "model.layers.0.self_attn.q_proj.weight": "pytorch_model-00001-of-00002.bin",
                    "model.layers.0.self_attn.k_proj.weight": "pytorch_model-00001-of-00002.bin",
                    "model.layers.0.self_attn.v_proj.weight": "pytorch_model-00001-of-00002.bin",
                    "model.layers.0.self_attn.o_proj.weight": "pytorch_model-00001-of-00002.bin",
                    "model.layers.0.self_attn.o_proj.bias": "pytorch_model-00001-of-00002.bin",
                    "model.layers.0.input_layernorm.weight": "pytorch_model-00002-of-00002.bin",
                    "model.layers.0.post_attention_layernorm.weight": "pytorch_model-00002-of-00002.bin",
                    "model.layers.0.mlp.up_proj.weight": "pytorch_model-00002-of-00002.bin",
                    "model.layers.0.mlp.gate_proj.weight": "pytorch_model-00002-of-00002.bin",
                    "model.layers.0.mlp.down_proj.weight": "pytorch_model-00002-of-00002.bin",
                    "model.norm.weight": "pytorch_model-00002-of-00002.bin",
                    "lm_head.weight": "pytorch_model-00002-of-00002.bin",
                },
            )

            saved_shards = []

            def fake_listdir(path):
                self.assertEqual(path, input_dir)
                return ["part1.safetensors", "notes.txt", "part2.safetensors"]

            def fake_isfile(path):
                return path in {file1, file2}

            def fake_safe_open(path, framework, device):
                self.assertEqual(framework, "pt")
                self.assertEqual(device, "cpu")
                return _FakeSafeOpen(path, framework, device, per_file_tensors)

            def fake_split_torch_state_dict_into_shards(state_dict, filename_pattern, max_shard_size):
                self.assertIn("{suffix}.bin", filename_pattern)
                self.assertEqual(max_shard_size, "1GB")
                self.assertEqual(len(state_dict), 13)
                return split_result

            def fake_torch_save(shard, path):
                saved_shards.append((path, sorted(shard.keys())))

            with patch.object(llamafy_qwen.os, "listdir", side_effect=fake_listdir), patch.object(
                llamafy_qwen.os.path, "isfile", side_effect=fake_isfile
            ), patch.object(llamafy_qwen, "safe_open", side_effect=fake_safe_open), patch.object(
                llamafy_qwen, "split_torch_state_dict_into_shards", side_effect=fake_split_torch_state_dict_into_shards
            ), patch.object(llamafy_qwen.torch, "save", side_effect=fake_torch_save), patch.object(
                llamafy_qwen, "tqdm", side_effect=lambda iterable, **kwargs: iterable
            ):
                torch_dtype = llamafy_qwen.save_weight(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    shard_size="1GB",
                    save_safetensors=False,
                )

            self.assertEqual(torch_dtype, "float32")
            self.assertEqual(len(saved_shards), 2)
            self.assertTrue(
                all(path.endswith(".bin") for path, _keys in saved_shards),
                "Expected all mocked shard outputs to be .bin files.",
            )

