import random
import unittest
from contextlib import ExitStack, nullcontext
from types import MethodType, SimpleNamespace
from unittest.mock import patch

import torch

import llamafactory.train.ppo.trainer as trainer_module
import llamafactory.train.ppo.workflow as workflow_module


class _ModelHarness:
    def __init__(self):
        self.training = True
        self.generation_count = 0

    def eval(self):
        self.training = False
        return self

    def train(self):
        self.training = True
        return self

    def generate(self, input_ids, attention_mask, **_kwargs):
        self.generation_count += 1
        rows = input_ids.size(0)
        offsets = torch.arange(rows, dtype=input_ids.dtype).unsqueeze(1)
        suffix = ((offsets + self.generation_count) % 17) + 3
        suffix = torch.cat((suffix, suffix + 19), dim=1)
        return torch.cat((input_ids, suffix), dim=1)


class _TokenizerHarness:
    pad_token_id = 0
    eos_token_id = 2
    additional_special_tokens_ids = []

    def __init__(self):
        self.padding_side = "left"

    def batch_decode(self, rows, **_kwargs):
        return ["|".join(str(int(token)) for token in row) for row in rows]


class _CallbackHarness:
    def __init__(self):
        self.events = []

    def on_train_begin(self, _args, _state, control):
        self.events.append(("begin", 0))
        return control

    def on_step_end(self, _args, state, control):
        self.events.append(("step", state.global_step))
        return control

    def on_log(self, _args, state, control, _logs):
        self.events.append(("log", state.global_step))
        return control

    def on_save(self, _args, state, control):
        self.events.append(("save", state.global_step))
        return control

    def on_train_end(self, _args, state, control):
        self.events.append(("end", state.global_step))
        return control


class TestIndirectPPOTrainingCallGraph(unittest.TestCase):
    def test_seeded_workflow_training(self):
        rng = random.Random(sum((index + 5) * ord(char) for index, char in enumerate(self.id())))
        model = _ModelHarness()
        tokenizer = _TokenizerHarness()
        callbacks = _CallbackHarness()
        rows = []
        for row_index in range(20):
            width = 5 + (row_index % 3)
            values = [rng.randrange(3, 97) for _ in range(width)]
            padded = [0] * (8 - width) + values
            rows.append(padded)

        batches = []
        for start in range(0, len(rows), 4):
            input_ids = torch.tensor(rows[start : start + 4], dtype=torch.long)
            batches.append({"input_ids": input_ids, "attention_mask": input_ids.ne(0).long()})

        args = SimpleNamespace(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=1,
            world_size=1,
            max_steps=len(rows) - len(batches),
            num_train_epochs=1,
            logging_steps=3,
            save_steps=4,
            output_dir="/tmp/unused-ppo-output",
            should_save=False,
            do_train=True,
            resume_from_checkpoint=None,
            save_safetensors=False,
        )
        finetuning_args = SimpleNamespace(
            ppo_buffer_size=2,
            ppo_epochs=3,
            reward_model_type="api",
            plot_loss=False,
        )
        model_args = SimpleNamespace(upcast_layernorm=False)
        trainer = trainer_module.CustomPPOTrainer.__new__(trainer_module.CustomPPOTrainer)
        trainer.args = args
        trainer.finetuning_args = finetuning_args
        trainer.model_args = model_args
        trainer.model = model
        trainer.reward_model = "deterministic-endpoint"
        trainer.tokenizer = tokenizer
        trainer.dataloader = batches
        trainer.dataset = rows
        trainer.config = SimpleNamespace(batch_size=4, mini_batch_size=2, log_with=None)
        trainer.state = SimpleNamespace(
            max_steps=0,
            num_train_epochs=0,
            is_local_process_zero=False,
            is_world_process_zero=False,
            global_step=0,
            log_history=[],
        )
        trainer.control = SimpleNamespace(should_epoch_stop=False, should_training_stop=False)
        trainer.callback_handler = callbacks
        trainer.accelerator = SimpleNamespace(unwrap_model=lambda current: current)
        trainer.amp_context = nullcontext()
        trainer.is_fsdp_enabled = False
        trainer.is_deepspeed_enabled = False
        trainer.generation_config = SimpleNamespace()
        trainer.is_local_process_zero = lambda: True
        trainer.is_world_process_zero = lambda: True
        trainer.save_state = lambda: None

        def fake_step(_self, queries, responses, rewards):
            weighted = sum(float(value) * (index + 1) for index, value in enumerate(rewards))
            token_mass = sum(int(response.sum()) for response in responses)
            return {
                "ppo/loss/total": (weighted + token_mass % 29) / (len(queries) * 37),
                "ppo/learning_rate": 1.0 / (97 + _self.state.global_step),
            }

        trainer.step = MethodType(fake_step, trainer)

        def fake_rewards(_endpoint, messages):
            return [
                torch.tensor(((sum(ord(char) for char in message) + index * index) % 41) / 7.0)
                for index, message in enumerate(messages)
            ]

        patches = [
            patch.object(workflow_module, "load_tokenizer", return_value={"tokenizer": tokenizer}),
            patch.object(workflow_module, "get_template_and_fix_tokenizer", return_value=object()),
            patch.object(
                workflow_module,
                "get_dataset",
                return_value={"train_dataset": rows, "eval_dataset": None},
            ),
            patch.object(workflow_module, "load_model", return_value=model),
            patch.object(workflow_module, "MultiModalDataCollatorForSeq2Seq", return_value=object()),
            patch.object(workflow_module, "create_ref_model", return_value=None),
            patch.object(workflow_module, "create_reward_model", return_value=trainer.reward_model),
            patch.object(workflow_module, "CustomPPOTrainer", side_effect=lambda **_kwargs: trainer),
            patch.object(trainer_module, "unwrap_model_for_generation", side_effect=lambda *_args: nullcontext(model)),
            patch.object(trainer_module, "get_logits_processor", return_value=[]),
            patch.object(trainer_module, "get_rewards_from_server", side_effect=fake_rewards),
            patch.object(trainer_module, "count_parameters", return_value=(len(rows) ** 2, len(rows) ** 2)),
            patch.object(trainer_module.logger, "info_rank0", return_value=None),
        ]

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            workflow_module.run_ppo(
                model_args,
                SimpleNamespace(),
                args,
                finetuning_args,
                SimpleNamespace(),
            )

        self.assertEqual(trainer.state.global_step, args.max_steps)
        self.assertEqual(model.generation_count, args.max_steps * 2)
        self.assertEqual(callbacks.events[0][0], "begin")
        self.assertEqual(callbacks.events[-1][0], "end")
        self.assertGreater(len(trainer.state.log_history), 3)
