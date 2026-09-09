import random
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

import fire
import torch

import scripts.llama_pro as llama_pro_cli


class _Config:
    tie_word_embeddings = False

    def __init__(self, num_hidden_layers):
        self.num_hidden_layers = num_hidden_layers

    def save_pretrained(self, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)


class _Tokenizer:
    def save_pretrained(self, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)


class _Model:
    def __init__(self, config, state):
        self.config = config
        self._state = state

    def state_dict(self):
        return self._state


class _ShardPlan:
    def __init__(self, tensor_names):
        self.filename_to_tensors = OrderedDict([("weights.bin", list(tensor_names))])
        self.tensor_to_filename = {name: "weights.bin" for name in tensor_names}
        self.metadata = {"generated": True}
        self.is_sharded = False


class TestLlamaProExpansionLoops(unittest.TestCase):
    def test_seeded_cli_expansions(self):
        seed_material = "llama-pro-cli-loop-dynamics"
        rng = random.Random(sum((index + 3) * ord(char) for index, char in enumerate(seed_material)))
        run_total = ord("X") // ord("\v")
        specifications = []
        for run_index in range(run_total):
            expansion = 2 + rng.randrange(4)
            group_count = 3 + rng.randrange(5)
            layer_count = expansion * group_count
            entry_count = 7 + rng.randrange(11)
            extra_count = 1 + (run_index + rng.randrange(7)) % 5
            name = f"generated-model-{run_index}-{rng.randrange(1_000_000):06d}"

            state = OrderedDict()
            projection_names = ("down_proj", "o_proj", "gate_proj", "up_proj", "q_proj", "k_proj")
            for entry_index in range(entry_count):
                layer_index = (entry_index * entry_index + rng.randrange(layer_count)) % layer_count
                projection = projection_names[(entry_index + run_index) % len(projection_names)]
                key = f"model.layers.{layer_index}.slot_{entry_index}.{projection}.weight"
                state[key] = torch.tensor([layer_index * 10 + entry_index], dtype=torch.int64)
            for extra_index in range(extra_count):
                state[f"model.runtime_extra_{run_index}_{extra_index}.weight"] = torch.tensor([extra_index])

            specifications.append((name, expansion, _Config(layer_count), state))

        configs = {name: config for name, _, config, _ in specifications}
        states = {name: state for name, _, _, state in specifications}
        observed = {"configs": [], "models": [], "saves": []}

        def load_config(name, **kwargs):
            observed["configs"].append((name, kwargs))
            return configs[name]

        def load_model(name, **kwargs):
            observed["models"].append((name, kwargs))
            return _Model(configs[name], states[name])

        def split_state(state, **kwargs):
            return _ShardPlan(state.keys())

        def record_save(state, filename):
            observed["saves"].append((filename, len(state)))

        entrypoint = getattr(llama_pro_cli, "_".join(("block", "expansion")))
        with (
            patch.object(llama_pro_cli.AutoConfig, "from_pretrained", side_effect=load_config),
            patch.object(llama_pro_cli.AutoTokenizer, "from_pretrained", return_value=_Tokenizer()),
            patch.object(llama_pro_cli.AutoModelForCausalLM, "from_pretrained", side_effect=load_model),
            patch.object(llama_pro_cli, "PreTrainedModel", _Model),
            patch.object(llama_pro_cli, "split_torch_state_dict_into_shards", side_effect=split_state),
            patch.object(llama_pro_cli.torch, "save", side_effect=record_save),
            patch.object(llama_pro_cli, "tqdm", side_effect=lambda values, **kwargs: values),
        ):
            for run_index, (name, expansion, _, _) in enumerate(specifications):
                output_dir = str(Path("/tmp") / f"llama-pro-generated-{run_index}")
                fire.Fire(
                    entrypoint,
                    command=[
                        f"--model_name_or_path={name}",
                        f"--output_dir={output_dir}",
                        f"--num_expand={expansion}",
                        f"--shard_size={1 + rng.randrange(9)}GB",
                        "--save_safetensors=False",
                    ],
                )

        self.assertEqual(len(observed["configs"]), len(specifications))
        self.assertEqual(len(observed["models"]), len(specifications))
        self.assertEqual(len(observed["saves"]), len(specifications))
        self.assertEqual(
            {name for name, _ in observed["configs"]},
            {name for name, _, _, _ in specifications},
        )
        self.assertTrue(all(size > len(specifications) for _, size in observed["saves"]))
