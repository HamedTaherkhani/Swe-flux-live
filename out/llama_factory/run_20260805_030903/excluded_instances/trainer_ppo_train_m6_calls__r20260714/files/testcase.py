import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import torch

sys.path.insert(0, "/testbed/src")
from llamafactory.train.ppo import trainer as trainer_mod


class _SingleBatchLoader:
    def __init__(self, batch):
        self._batch = batch

    def __iter__(self):
        return iter([self._batch])


class _DummyTokenizer:
    pad_token_id = 0
    eos_token_id = 2
    additional_special_tokens_ids = [3]

    def __init__(self):
        self.padding_side = "left"

    def batch_decode(self, sequences, skip_special_tokens=True):
        decoded = []
        for item in sequences:
            if isinstance(item, torch.Tensor):
                tokens = item.detach().cpu().tolist()
            else:
                tokens = list(item)
            decoded.append(" ".join(str(tok) for tok in tokens))
        return decoded


class _DummyModel:
    def __init__(self):
        self.mode = "train"

    def eval(self):
        self.mode = "eval"
        return self

    def train(self):
        self.mode = "train"
        return self

    def generate(self, generation_config=None, logits_processor=None, **batch):
        input_ids = batch["input_ids"]
        suffix = torch.full((input_ids.size(0), 2), 7, dtype=input_ids.dtype)
        return torch.cat([input_ids, suffix], dim=1)

    def parameters(self):
        return [torch.nn.Parameter(torch.ones(1))]


class _DummyCallbackHandler:
    def __init__(self):
        self.train_begin = 0
        self.step_end = 0
        self.log_calls = 0
        self.save_calls = 0
        self.train_end = 0

    def on_train_begin(self, args, state, control):
        self.train_begin += 1
        return control

    def on_step_end(self, args, state, control):
        self.step_end += 1
        return control

    def on_log(self, args, state, control, logs):
        self.log_calls += 1
        return control

    def on_save(self, args, state, control):
        self.save_calls += 1
        return control

    def on_train_end(self, args, state, control):
        self.train_end += 1
        return control


class _DummyAccelerator:
    def unwrap_model(self, model):
        return model


class TestPPOTrainM6Calls(unittest.TestCase):
    def test_call_frequency_and_first_caller(self):
        torch.manual_seed(0)

        trainer = trainer_mod.CustomPPOTrainer.__new__(trainer_mod.CustomPPOTrainer)
        trainer.args = SimpleNamespace(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=1,
            world_size=1,
            max_steps=3,
            num_train_epochs=1,
            logging_steps=2,
            save_steps=2,
            output_dir="/tmp/ppo_train_m6_calls",
            should_save=False,
        )
        trainer.finetuning_args = SimpleNamespace(
            ppo_buffer_size=4,
            ppo_epochs=1,
            reward_model_type="api",
        )
        trainer.config = SimpleNamespace(batch_size=4, mini_batch_size=1, log_with=None)
        trainer.state = SimpleNamespace(
            max_steps=0,
            num_train_epochs=0,
            is_local_process_zero=False,
            is_world_process_zero=False,
            global_step=0,
            log_history=[],
        )
        trainer.control = SimpleNamespace(should_epoch_stop=False, should_training_stop=False)
        trainer.callback_handler = _DummyCallbackHandler()
        trainer.is_local_process_zero = lambda: True
        trainer.is_world_process_zero = lambda: True
        trainer.model = _DummyModel()
        trainer.tokenizer = _DummyTokenizer()
        trainer.generation_config = object()
        trainer.model_args = SimpleNamespace(upcast_layernorm=False)
        trainer.accelerator = _DummyAccelerator()
        trainer.reward_model = object()
        trainer.is_fsdp_enabled = False
        trainer.is_deepspeed_enabled = False
        trainer.dataset = [0, 1, 2, 3]

        batch = {
            "input_ids": torch.tensor(
                [
                    [0, 0, 11, 12],
                    [0, 13, 14, 15],
                    [16, 17, 18, 19],
                    [0, 0, 0, 20],
                ],
                dtype=torch.long,
            ),
            "attention_mask": torch.tensor(
                [
                    [0, 0, 1, 1],
                    [0, 1, 1, 1],
                    [1, 1, 1, 1],
                    [0, 0, 0, 1],
                ],
                dtype=torch.long,
            ),
        }
        trainer.dataloader = _SingleBatchLoader(batch)
        trainer.step = lambda queries, responses, rewards: {
            "ppo/loss/total": float(len(rewards)),
            "ppo/learning_rate": 0.001,
        }

        @contextmanager
        def _fake_unwrap_model_for_generation(model, accelerator):
            yield model

        def _fake_get_rewards_from_server(reward_model, messages):
            return [torch.tensor(float(idx + 1)) for idx, _ in enumerate(messages)]

        def _fake_tqdm(iterable, disable=False):
            return iterable

        _fake_tqdm.write = lambda _msg: None

        with (
            mock.patch.object(trainer_mod, "unwrap_model_for_generation", _fake_unwrap_model_for_generation),
            mock.patch.object(trainer_mod, "get_rewards_from_server", _fake_get_rewards_from_server),
            mock.patch.object(trainer_mod, "get_logits_processor", lambda: None),
            mock.patch.object(trainer_mod, "tqdm", _fake_tqdm),
        ):
            trainer_mod.CustomPPOTrainer.ppo_train(trainer)

        self.assertEqual(trainer.state.global_step, 3)
        self.assertEqual(trainer.callback_handler.train_begin, 1)
        self.assertEqual(trainer.callback_handler.step_end, 3)
        self.assertEqual(trainer.callback_handler.log_calls, 1)
        self.assertEqual(trainer.callback_handler.save_calls, 1)
        self.assertEqual(trainer.callback_handler.train_end, 1)
        self.assertEqual(len(trainer.state.log_history), 1)
        self.assertEqual(trainer.tokenizer.padding_side, "left")
