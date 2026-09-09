import json
import random
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _module(name, package=False, **attributes):
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


class _Tokenizer:
    def decode(self, token_ids, skip_special_tokens=True):
        modulus = (80 + 9) if skip_special_tokens else (80 + 17)
        return "decoded-" + "-".join(str((token * (index + 3)) % modulus) for index, token in enumerate(token_ids))


class BasePlugin:
    def __init__(self):
        self.expand_mm_tokens = True

    def _regularize_images(self, images, **kwargs):
        return {"images": [("image", value, sum(kwargs.values())) for value in images]}

    def _regularize_videos(self, videos, **kwargs):
        return {"videos": [("video", value, sum(kwargs.values())) for value in videos]}

    def _regularize_audios(self, audios, sampling_rate):
        return {
            "audios": [value * 2 + index for index, value in enumerate(audios)],
            "sampling_rates": [sampling_rate + index for index in range(len(audios))],
        }

    def get_stop_token_ids(self, tokenizer):
        return [3, 5, 8]


class _RichPlugin(BasePlugin):
    pass


class _Template:
    def __init__(self, rich):
        self.mm_plugin = _RichPlugin() if rich else BasePlugin()

    def get_stop_token_ids(self, tokenizer):
        return self.mm_plugin.get_stop_token_ids(tokenizer)


class _SamplingParams:
    def __init__(self, **kwargs):
        self.values = kwargs


class _LoRARequest:
    def __init__(self, name, rank, path):
        self.name = name
        self.rank = rank
        self.path = path


class _Result:
    def __init__(self, text):
        self.outputs = [SimpleNamespace(text=text)]


class _LLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def generate(self, inputs, sampling_params, lora_request=None):
        salt = len(self.kwargs) + len(sampling_params.values) + (lora_request.rank if lora_request else 0)
        return [
            _Result("prediction-" + str((sum(item["prompt_token_ids"]) + salt + index * index) % 1009))
            for index, item in enumerate(inputs)
        ]


class TestVllmInferDataFlow(unittest.TestCase):
    def test_seeded_cli_entrypoint_multimodal_batches(self):
        seed = sum((index + 7) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        state = {"scenario": 0, "written": []}

        def get_infer_args(raw):
            scenario = int(raw["model_name_or_path"].rsplit("-", 1)[1])
            state["scenario"] = scenario
            model_args = SimpleNamespace(
                model_name_or_path=raw["model_name_or_path"],
                adapter_name_or_path=None if scenario % 2 == 0 else [f"adapter-{scenario}"],
                infer_dtype="float16" if scenario != 2 else "bfloat16",
                vllm_config={"block_size": 8 + scenario, "swap_space": scenario + 1}
                if scenario != 1
                else "disabled",
            )
            data_args = SimpleNamespace(scenario=scenario)
            generating_args = SimpleNamespace(
                repetition_penalty=0.0 if scenario == 0 else 1.03 + scenario / (10 * 10),
                temperature=0.2 + scenario / 10,
                top_p=0.0 if scenario == 1 else 0.81,
                top_k=0 if scenario == 2 else 23 + scenario,
                max_new_tokens=7 + scenario,
            )
            return model_args, data_args, None, generating_args

        def load_tokenizer(model_args):
            return {"tokenizer": _Tokenizer(), "processor": SimpleNamespace(model=model_args.model_name_or_path)}

        def get_template_and_fix_tokenizer(tokenizer, data_args):
            return _Template(rich=data_args.scenario != 1)

        def get_dataset(template_obj, model_args, data_args, training_args, stage, **tokenizer_module):
            samples = []
            for index in range(18 + data_args.scenario):
                width = 5 + (index * 3 + data_args.scenario) % 7
                token_ids = [
                    3 + (rng.randrange(101 + 12) + index * index + position * (data_args.scenario + 2)) % 127
                    for position in range(width)
                ]
                labels = [
                    -(10**2) if (position + index + data_args.scenario) % 4 == 0 else token ^ (index + position)
                    for position, token in enumerate(token_ids)
                ]
                mode = (index + data_args.scenario) % 4
                samples.append(
                    {
                        "input_ids": token_ids,
                        "labels": labels,
                        "images": [rng.randrange(1000) for _ in range(1 + index % 3)] if mode == 0 else [],
                        "videos": [rng.randrange(1000) for _ in range(1 + index % 2)] if mode == 1 else [],
                        "audios": [rng.randrange(1000) for _ in range(1 + index % 4)] if mode == 2 else [],
                    }
                )
            return {"train_dataset": samples}

        def fire_entrypoint(command):
            with tempfile.TemporaryDirectory() as directory:
                destination = Path(directory)
                for scenario in range(3):
                    output = destination / f"batch-{scenario}.jsonl"
                    options = {
                        "model_name_or_path": f"generated-model-{scenario}",
                        "dataset": "generated-dataset",
                        "save_name": str(output),
                        "cutoff_len": 41 + scenario,
                        "max_new_tokens": 7 + scenario,
                        "pipeline_parallel_size": 1 + scenario % 2,
                        "image_max_pixels": 400 + scenario * 17,
                        "image_min_pixels": 20 + scenario * 3,
                        "seed": seed + scenario,
                    }
                    command(**options)
                    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
                    state["written"].append(records)

        fake_modules = {
            "fire": _module("fire", Fire=fire_entrypoint),
            "transformers": _module(
                "transformers",
                Seq2SeqTrainingArguments=lambda **kwargs: SimpleNamespace(**kwargs),
            ),
            "llamafactory": _module("llamafactory", package=True),
            "llamafactory.data": _module(
                "llamafactory.data",
                get_dataset=get_dataset,
                get_template_and_fix_tokenizer=get_template_and_fix_tokenizer,
            ),
            "llamafactory.extras": _module("llamafactory.extras", package=True),
            "llamafactory.extras.constants": _module(
                "llamafactory.extras.constants",
                IGNORE_INDEX=-(10**2),
            ),
            "llamafactory.extras.misc": _module(
                "llamafactory.extras.misc",
                check_version=lambda requirement: None,
                get_device_count=lambda: 4,
            ),
            "llamafactory.extras.packages": _module(
                "llamafactory.extras.packages",
                is_vllm_available=lambda: True,
            ),
            "llamafactory.hparams": _module("llamafactory.hparams", get_infer_args=get_infer_args),
            "llamafactory.model": _module("llamafactory.model", load_tokenizer=load_tokenizer),
            "vllm": _module("vllm", package=True, LLM=_LLM, SamplingParams=_SamplingParams),
            "vllm.lora": _module("vllm.lora", package=True),
            "vllm.lora.request": _module("vllm.lora.request", LoRARequest=_LoRARequest),
        }

        with patch.dict(sys.modules, fake_modules):
            runpy.run_module("scripts.vllm_infer", run_name="__main__")

        self.assertEqual(len(state["written"]), 3)
        self.assertTrue(all(len(batch) >= 18 for batch in state["written"]))
        self.assertTrue(all(set(record) == {"prompt", "predict", "label"} for batch in state["written"] for record in batch))
        self.assertTrue(all(record["predict"].startswith("prediction-") for batch in state["written"] for record in batch))
