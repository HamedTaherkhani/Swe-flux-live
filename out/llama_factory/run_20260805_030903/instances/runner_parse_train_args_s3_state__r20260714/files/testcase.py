import random
import unittest
from unittest.mock import patch

from src.llamafactory.webui.runner import Runner


class _DummyManager:
    def get_elem_by_id(self, elem_id):
        return elem_id


def _base_payload():
    return {
        "top.model_name": "TinyModel",
        "top.finetuning_type": "lora",
        "top.model_path": "/models/tiny",
        "top.template": "default",
        "top.rope_scaling": "none",
        "top.booster": "flashattn2",
        "top.checkpoint_path": [],
        "top.quantization_bit": "none",
        "top.quantization_method": "bnb",
        "train.training_stage": "Supervised Fine-Tuning",
        "train.dataset_dir": "data",
        "train.dataset": ["alpaca", "sharegpt"],
        "train.cutoff_len": 1024,
        "train.learning_rate": "0.0002",
        "train.num_train_epochs": "3.0",
        "train.max_samples": "200",
        "train.batch_size": 4,
        "train.gradient_accumulation_steps": 8,
        "train.lr_scheduler_type": "cosine",
        "train.max_grad_norm": "1.0",
        "train.logging_steps": 5,
        "train.save_steps": 20,
        "train.warmup_steps": 0,
        "train.neftune_alpha": 0.0,
        "train.packing": False,
        "train.neat_packing": True,
        "train.train_on_prompt": False,
        "train.mask_history": False,
        "train.resize_vocab": True,
        "train.use_llama_pro": False,
        "train.report_to": ["tensorboard"],
        "train.use_galore": False,
        "train.use_apollo": False,
        "train.use_badam": False,
        "train.use_swanlab": False,
        "train.output_dir": "trial_out",
        "train.compute_type": "bf16",
        "train.extra_args": "{}",
        "train.freeze_trainable_layers": 1,
        "train.freeze_trainable_modules": "all",
        "train.freeze_extra_modules": "",
        "train.lora_rank": 8,
        "train.lora_alpha": 16,
        "train.lora_dropout": 0.05,
        "train.loraplus_lr_ratio": 0.0,
        "train.create_new_adapter": True,
        "train.use_rslora": True,
        "train.use_dora": False,
        "train.use_pissa": True,
        "train.lora_target": "",
        "train.additional_target": "",
        "train.reward_model": ["reward_adapter"],
        "train.ppo_score_norm": True,
        "train.ppo_whiten_rewards": False,
        "train.pref_beta": 0.1,
        "train.pref_ftx": 0.25,
        "train.pref_loss": "sigmoid",
        "train.galore_rank": 32,
        "train.galore_update_interval": 100,
        "train.galore_scale": 0.25,
        "train.galore_target": "all",
        "train.apollo_rank": 24,
        "train.apollo_update_interval": 75,
        "train.apollo_scale": 0.3,
        "train.apollo_target": "attn,mlp",
        "train.badam_mode": "layer",
        "train.badam_switch_mode": "random",
        "train.badam_switch_interval": 3,
        "train.badam_update_ratio": 0.12,
        "train.swanlab_project": "proj",
        "train.swanlab_run_name": "run",
        "train.swanlab_workspace": "team",
        "train.swanlab_api_key": "token",
        "train.swanlab_mode": "offline",
        "train.val_size": 0.0,
        "train.ds_stage": "none",
        "train.ds_offload": False,
    }


class TestRunnerParseTrainArgsS3State(unittest.TestCase):
    def test_second_invocation_return_state(self):
        random.seed(7)
        runner = Runner(manager=_DummyManager(), demo_mode=False)

        first = _base_payload()
        first.update(
            {
                "train.training_stage": "PPO",
                "train.reward_model": ["reward_adapter_a", "reward_adapter_b"],
                "top.checkpoint_path": ["ckpt_one"],
                "top.quantization_bit": "8",
                "train.report_to": ["all"],
            }
        )

        second = _base_payload()
        second.update(
            {
                "train.training_stage": "DPO",
                "top.checkpoint_path": ["alpha_adapter", "beta_adapter"],
                "top.quantization_bit": "4",
                "train.use_llama_pro": True,
                "train.report_to": ["tensorboard", "none", "all"],
                "train.use_galore": True,
                "train.use_apollo": True,
                "train.use_badam": True,
                "train.use_swanlab": True,
                "train.val_size": 0.2,
                "train.ds_stage": "3",
                "train.ds_offload": True,
                "train.extra_args": '{"save_steps": 88, "custom_flag": "enabled"}',
            }
        )

        with patch("src.llamafactory.webui.runner.load_config", return_value={"cache_dir": "custom-cache"}), patch(
            "src.llamafactory.webui.runner.is_torch_npu_available", return_value=False
        ):
            first_args = runner._parse_train_args(first)
            second_args = runner._parse_train_args(second)

        self.assertEqual(first_args["stage"], "ppo")
        self.assertIn("reward_model", first_args)
        self.assertEqual(first_args["report_to"], "all")
        self.assertTrue(first_args["adapter_name_or_path"].endswith("saves/TinyModel/lora/ckpt_one"))

        self.assertEqual(second_args["stage"], "dpo")
        self.assertEqual(second_args["report_to"], "none")
        self.assertEqual(second_args["pref_loss"], "sigmoid")
        self.assertEqual(second_args["eval_steps"], 88)
        self.assertEqual(second_args["custom_flag"], "enabled")
        self.assertEqual(second_args["deepspeed"], "cache/ds_z3_offload_config.json")
        self.assertIn("saves/TinyModel/lora/alpha_adapter", second_args["adapter_name_or_path"])
        self.assertIn("saves/TinyModel/lora/beta_adapter", second_args["adapter_name_or_path"])
