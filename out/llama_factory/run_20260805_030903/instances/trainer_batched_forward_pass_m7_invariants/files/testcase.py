import contextlib
import random
import unittest
from types import MethodType, SimpleNamespace

import torch

from llamafactory.train.ppo.trainer import CustomPPOTrainer


class _DeterministicValueModel:
    def __init__(self):
        self.calls = 0

    def __call__(self, input_ids, attention_mask, return_dict, use_cache):
        if not return_dict or use_cache:
            raise RuntimeError("unexpected model call mode")
        self.calls += 1
        vocab_axis = torch.arange(61, dtype=torch.float32)
        centers = (input_ids * 7 + attention_mask * 11 + self.calls) % 61
        logits = -(vocab_axis.view(1, 1, -1) - centers.unsqueeze(-1)).abs()
        values = (
            input_ids.float() / 32
            + attention_mask.float() / 8
            + self.calls * 0.0005
        )
        return logits, None, values


def _prepare_inputs(self, queries, responses):
    combined = [torch.cat((query, response)) for query, response in zip(queries, responses)]
    width = max(len(row) for row in combined)
    input_ids = torch.zeros((len(combined), width), dtype=torch.long)
    attention_mask = torch.zeros_like(input_ids)
    for index, row in enumerate(combined):
        left_pad = (index * index + len(row)) % 4
        usable_left = min(left_pad, width - len(row))
        start = usable_left if index % 3 else 0
        input_ids[index, start : start + len(row)] = row
        attention_mask[index, start : start + len(row)] = 1
    return {"input_ids": input_ids, "attention_mask": attention_mask}


@contextlib.contextmanager
def _stop_before_reference_pass():
    raise RuntimeError("reference checkpoint reached")
    yield


class TestBatchedForwardRuntime(unittest.TestCase):
    def test_seeded_step_observations(self):
        seed = sum((index + 3) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)
        sample_count = sum((index * index + 5 * index + 7) % 9 for index in range(5))

        queries = []
        responses = []
        scores = []
        for index in range(sample_count):
            query_length = 3 + (rng.randrange(10_000) + index * index) % 7
            response_length = 1 + (rng.randrange(10_000) ^ (index * 13)) % 7
            query = torch.tensor(
                [2 + (rng.randrange(53) + index + offset * offset) % 53 for offset in range(query_length)]
            )
            response = torch.tensor(
                [2 + (rng.randrange(53) + 3 * index + 5 * offset) % 53 for offset in range(response_length)]
            )
            queries.append(query)
            responses.append(response)
            scores.append(torch.tensor((index % 11 - 5) / 7.0))

        trainer = object.__new__(CustomPPOTrainer)
        trainer.config = SimpleNamespace(
            batch_size=sample_count,
            mini_batch_size=1,
            use_score_scaling=False,
            score_clip=None,
            kl_penalty="full",
        )
        trainer.current_device = torch.device("cpu")
        trainer.is_distributed = False
        trainer.is_peft_model = False
        trainer.model = _DeterministicValueModel()
        trainer.ref_model = _DeterministicValueModel()
        trainer.amp_context = contextlib.nullcontext()
        trainer.optional_peft_ctx = _stop_before_reference_pass
        trainer.prepare_model_inputs = MethodType(_prepare_inputs, trainer)

        with self.assertRaisesRegex(RuntimeError, "checkpoint"):
            trainer.step(queries, responses, scores)

        self.assertGreater(trainer.model.calls, 0)
        self.assertFalse(trainer.ref_model.calls)
