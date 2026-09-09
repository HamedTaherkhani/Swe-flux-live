import random
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from transformers.training_args import ParallelMode

from llamafactory.hparams import parser as parser_module
from llamafactory.train import tuner


class TestTrainArgumentControlFlow(unittest.TestCase):
    def test_three_indirect_training_configurations(self):
        rng = random.Random(sum(ord(ch) for ch in self.id()))

        def namespace(**overrides):
            values = {
                "additional_target": None,
                "adapter_name_or_path": None,
                "apollo_layerwise": False,
                "badam_mode": "layer",
                "bf16": False,
                "block_diag_attn": False,
                "compute_accuracy": False,
                "compute_dtype": None,
                "create_new_adapter": False,
                "cutoff_len": rng.randrange(512, 1024),
                "dataset": "generated-" + str(rng.randrange(1000, 9999)),
                "ddp_find_unused_parameters": None,
                "deepspeed": None,
                "device": "cpu",
                "device_map": None,
                "do_eval": False,
                "do_predict": False,
                "do_train": True,
                "enable_liger_kernel": False,
                "eval_dataset": None,
                "finetuning_type": "lora",
                "fp16": False,
                "galore_layerwise": False,
                "infer_backend": "huggingface",
                "load_best_model_at_end": False,
                "mask_history": False,
                "max_steps": rng.randrange(10, 40),
                "mixture_of_depths": None,
                "model_max_length": None,
                "neat_packing": False,
                "output_dir": "",
                "overwrite_output_dir": False,
                "packing": None,
                "parallel_mode": ParallelMode.DISTRIBUTED,
                "pissa_convert": False,
                "pissa_init": False,
                "plot_loss": False,
                "predict_with_generate": False,
                "process_index": 0,
                "pure_bf16": False,
                "quantization_bit": None,
                "quantization_device_map": None,
                "ref_model": None,
                "report_to": [],
                "resize_vocab": False,
                "resume_from_checkpoint": None,
                "reward_model_type": "full",
                "seed": rng.randrange(1000, 9999),
                "shift_attn": False,
                "should_log": False,
                "stage": "sft",
                "streaming": False,
                "template": "default",
                "train_on_prompt": False,
                "upcast_layernorm": True,
                "use_adam_mini": False,
                "use_apollo": False,
                "use_badam": False,
                "use_fast_tokenizer": True,
                "use_galore": False,
                "use_swanlab": False,
                "use_unsloth": False,
                "val_size": 0.0,
                "world_size": 2,
            }
            values.update(overrides)
            return SimpleNamespace(**values)

        with tempfile.TemporaryDirectory() as temp_dir:
            configs = []

            first_model = namespace(resize_vocab=True)
            first_data = namespace(stage="pt", packing=None, output_dir=temp_dir + "/first")
            first_training = namespace(output_dir=temp_dir + "/first", streaming=True)
            first_finetuning = namespace(stage="pt")
            configs.append((first_model, first_data, first_training, first_finetuning, namespace()))

            second_model = namespace(resize_vocab=True)
            second_data = namespace(
                do_eval=True,
                eval_dataset="eval-" + str(rng.randrange(1000, 9999)),
                neat_packing=True,
                packing=False,
                template="yi",
            )
            second_training = namespace(
                do_eval=True,
                output_dir=temp_dir + "/second",
                predict_with_generate=True,
                report_to=["tensorboard"],
            )
            second_finetuning = namespace(stage="sft")
            configs.append((second_model, second_data, second_training, second_finetuning, namespace()))

            third_model = namespace(quantization_bit=4, upcast_layernorm=False)
            third_data = namespace(dataset=None, packing=None)
            third_training = namespace(do_train=False, output_dir=temp_dir + "/third")
            third_finetuning = namespace(stage="dpo")
            configs.append((third_model, third_data, third_training, third_finetuning, namespace()))

            stage_runners = {name: Mock() for name in ("run_pt", "run_sft", "run_dpo")}
            with (
                patch.object(parser_module, "_parse_train_args", side_effect=configs),
                patch.object(tuner, "get_ray_args", return_value=SimpleNamespace(use_ray=False)),
                patch.object(tuner, "LogCallback", side_effect=lambda: object()),
                patch.object(tuner, "ReporterCallback", side_effect=lambda *args: object()),
                patch.multiple(tuner, **stage_runners),
            ):
                for index in range(len(configs)):
                    tuner.run_exp({"scenario": index}, callbacks=[])

            self.assertEqual(sum(runner.call_count for runner in stage_runners.values()), len(configs))
            self.assertTrue(second_data.packing)
            self.assertFalse(second_training.ddp_find_unused_parameters)

