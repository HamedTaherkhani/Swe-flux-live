import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch
from transformers.training_args import ParallelMode

from src.llamafactory.hparams import parser as parser_mod


def _make_model_args(**overrides):
    base = {
        "shift_attn": False,
        "use_unsloth": False,
        "quantization_device_map": None,
        "infer_backend": "huggingface",
        "quantization_bit": None,
        "resize_vocab": False,
        "upcast_layernorm": False,
        "compute_dtype": None,
        "device_map": None,
        "model_max_length": None,
        "block_diag_attn": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_data_args(**overrides):
    base = {
        "neat_packing": False,
        "train_on_prompt": False,
        "mask_history": False,
        "streaming": False,
        "dataset": None,
        "eval_dataset": None,
        "val_size": 0.0,
        "packing": None,
        "cutoff_len": 1024,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_training_args(**overrides):
    base = {
        "should_log": False,
        "predict_with_generate": False,
        "do_predict": False,
        "load_best_model_at_end": False,
        "do_train": True,
        "report_to": [],
        "parallel_mode": ParallelMode.DISTRIBUTED,
        "deepspeed": None,
        "max_steps": 10,
        "do_eval": False,
        "ddp_find_unused_parameters": None,
        "resume_from_checkpoint": None,
        "output_dir": "/testbed/llama_factory_qa/tmp_nonexistent_dir",
        "overwrite_output_dir": True,
        "bf16": False,
        "fp16": False,
        "process_index": 0,
        "world_size": 1,
        "device": "cpu",
        "seed": 17,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_finetuning_args(**overrides):
    base = {
        "stage": "sft",
        "reward_model_type": "lora",
        "use_galore": False,
        "galore_layerwise": False,
        "use_apollo": False,
        "apollo_layerwise": False,
        "use_badam": False,
        "badam_mode": "layer",
        "pissa_init": False,
        "pure_bf16": False,
        "finetuning_type": "lora",
        "additional_target": None,
        "compute_accuracy": False,
        "ref_model": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestParserGetTrainArgsCFG(unittest.TestCase):
    def test_three_invocations_cfg_path(self):
        random.seed(1234)
        torch.manual_seed(1234)

        parse_returns = [
            (
                _make_model_args(resize_vocab=True),
                _make_data_args(dataset=["train_a"]),
                _make_training_args(should_log=True, do_train=True, seed=101),
                _make_finetuning_args(stage="sft", finetuning_type="lora", additional_target=None),
                SimpleNamespace(),
            ),
            (
                _make_model_args(quantization_bit=4),
                _make_data_args(dataset=None, eval_dataset=["eval_a"]),
                _make_training_args(
                    do_train=False,
                    do_eval=True,
                    fp16=True,
                    overwrite_output_dir=False,
                    output_dir="/testbed/llama_factory_qa/tmp_eval_dir",
                    seed=202,
                ),
                _make_finetuning_args(stage="dpo", finetuning_type="lora", ref_model=None),
                SimpleNamespace(),
            ),
            (
                _make_model_args(),
                _make_data_args(dataset=["train_c"]),
                _make_training_args(
                    should_log=True,
                    do_train=True,
                    bf16=True,
                    resume_from_checkpoint="/tmp/pretend_ckpt",
                    overwrite_output_dir=False,
                    output_dir="/testbed/llama_factory_qa/tmp_train_dir",
                    seed=303,
                ),
                _make_finetuning_args(stage="rm", finetuning_type="full"),
                SimpleNamespace(),
            ),
        ]

        with patch.object(parser_mod, "_parse_train_args", side_effect=parse_returns) as mock_parse, patch.object(
            parser_mod, "_set_transformers_logging", autospec=True
        ) as mock_set_logging, patch.object(
            parser_mod, "_verify_model_args", autospec=True
        ) as mock_verify, patch.object(
            parser_mod, "_check_extra_dependencies", autospec=True
        ) as mock_check_deps, patch.object(
            parser_mod, "is_deepspeed_zero3_enabled", autospec=True, return_value=False
        ):
            outputs = [parser_mod.get_train_args({}) for _ in range(3)]

        self.assertEqual(mock_parse.call_count, 3)
        self.assertEqual(mock_set_logging.call_count, 2)
        self.assertEqual(mock_verify.call_count, 3)
        self.assertEqual(mock_check_deps.call_count, 3)
        self.assertEqual(len(outputs), 3)
        self.assertEqual(outputs[0][0].model_max_length, 1024)
        self.assertEqual(outputs[1][0].compute_dtype, torch.float16)
        self.assertEqual(outputs[2][0].compute_dtype, torch.bfloat16)
        self.assertEqual(outputs[2][2].resume_from_checkpoint, None)
