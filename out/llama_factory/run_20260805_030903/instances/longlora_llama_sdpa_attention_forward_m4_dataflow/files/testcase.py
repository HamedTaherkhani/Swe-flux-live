import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch
from torch import nn

from llamafactory.model.model_utils import longlora as longlora_module


def _seeded_linear(rng, in_features, out_features):
    layer = nn.Linear(in_features, out_features, bias=False)
    values = [rng.uniform(-0.8, 0.8) for _ in range(in_features * out_features)]
    with torch.no_grad():
        layer.weight.copy_(torch.tensor(values).reshape(out_features, in_features))
    return layer


def _rotary_mix(query, key, cos, sin):
    query_rotated = query.roll(1, dims=-1)
    key_rotated = key.roll(1, dims=-1)
    return query * cos + query_rotated * sin, key * cos - key_rotated * sin


class _GeneratedCache:
    def __init__(self, salt):
        self.salt = salt
        self.calls = 0

    def update(self, key, value, layer_index, cache_kwargs):
        self.calls += 1
        phase = cache_kwargs["cos"].mean() + cache_kwargs["sin"].mean()
        adjustment = key.new_tensor(self.salt + layer_index + self.calls) * phase / 100
        return key + adjustment, value - adjustment


class _GeneratedAttention(nn.Module):
    def __init__(self, rng):
        super().__init__()
        self.num_heads = 4
        self.num_key_value_heads = 2
        self.num_key_value_groups = self.num_heads // self.num_key_value_heads
        self.head_dim = 2
        self.hidden_size = self.num_heads * self.head_dim
        self.attention_dropout = 0.0
        self.layer_idx = 1 + rng.randrange(5)
        self.config = SimpleNamespace(group_size_ratio=0.25)
        self.q_proj = _seeded_linear(rng, self.hidden_size, self.hidden_size)
        self.k_proj = _seeded_linear(rng, self.hidden_size, self.num_key_value_heads * self.head_dim)
        self.v_proj = _seeded_linear(rng, self.hidden_size, self.num_key_value_heads * self.head_dim)
        self.o_proj = _seeded_linear(rng, self.hidden_size, self.hidden_size)

    def rotary_emb(self, value_states, position_ids):
        phase = value_states.cumsum(dim=2).mean(dim=1, keepdim=True)
        return torch.cos(phase), torch.sin(phase)


setattr(
    _GeneratedAttention,
    "forward",
    getattr(longlora_module, "_".join(("llama", "sdpa", "attention", "forward"))),
)


class _AttentionPipeline(nn.Module):
    def __init__(self, rng):
        super().__init__()
        self.block = _GeneratedAttention(rng)

    def forward(self, hidden_states, mask_values, scenario):
        self.block.train(scenario % 2 == 0)
        sequence_length = hidden_states.size(1)
        attention_mask = None
        if scenario % 4 != 1:
            attention_mask = mask_values[:, None, None, :].expand(
                -1, 1, sequence_length, -1
            )

        position_embeddings = None
        if scenario % 3 != 2:
            phase = hidden_states.cumsum(dim=1).mean(dim=-1, keepdim=True)
            cos = torch.cos(phase).unsqueeze(1).expand(
                -1, 1, -1, self.block.head_dim
            )
            sin = torch.sin(phase).unsqueeze(1).expand_as(cos)
            position_embeddings = (cos, sin)

        cache = None
        if scenario % 5 in (1, 3):
            cache = _GeneratedCache((scenario * scenario + sequence_length) % 17)

        return self.block(
            hidden_states,
            attention_mask=attention_mask,
            position_ids=torch.arange(sequence_length).unsqueeze(0),
            past_key_value=cache,
            output_attentions=scenario % 7 == 0,
            cache_position=torch.arange(sequence_length),
            position_embeddings=position_embeddings,
        )


class TestLongLoraSdpaDataFlow(unittest.TestCase):
    def test_seeded_attention_branch_matrix_through_pipeline(self):
        seed = sum(
            (index + 7) * ord(character)
            for index, character in enumerate(self.id())
        )
        rng = random.Random(seed)
        torch.manual_seed(seed % (2**31))
        pipeline = _AttentionPipeline(rng)
        results = []

        with patch.object(
            longlora_module, "apply_rotary_pos_emb", side_effect=_rotary_mix
        ):
            for scenario in range(20):
                sequence_length = 16 + 4 * (scenario % 4)
                features = [
                    rng.uniform(-1.0, 1.0)
                    + ((row + 3) * (column + scenario + 5) % 19) / 23
                    for row in range(sequence_length)
                    for column in range(pipeline.block.hidden_size)
                ]
                hidden_states = torch.tensor(features, dtype=torch.float32).reshape(
                    1, sequence_length, pipeline.block.hidden_size
                )
                mask_values = torch.tensor(
                    [
                        -float(
                            (rng.randrange(11) + position * position + scenario) % 7
                        )
                        for position in range(sequence_length)
                    ],
                    dtype=torch.float32,
                ).unsqueeze(0)
                results.append(pipeline(hidden_states, mask_values, scenario))

        self.assertEqual(len(results), 20)
        self.assertTrue(
            all(
                output.shape[0] == 1
                and output.shape[2] == pipeline.block.hidden_size
                and torch.isfinite(output).all()
                for output, _, _ in results
            )
        )
        self.assertTrue(any(weights is not None for _, weights, _ in results))
        self.assertTrue(any(cache is not None for _, _, cache in results))
