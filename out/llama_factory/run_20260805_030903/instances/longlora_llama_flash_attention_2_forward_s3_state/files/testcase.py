import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch
from torch import nn

from llamafactory.model.model_utils import longlora as longlora_module


def _seeded_linear(rng, in_features, out_features):
    layer = nn.Linear(in_features, out_features, bias=False)
    values = [rng.uniform(-0.7, 0.7) for _ in range(in_features * out_features)]
    with torch.no_grad():
        layer.weight.copy_(torch.tensor(values).reshape(out_features, in_features))
    return layer


def _rotary_mix(query, key, cos, sin):
    return query * cos + query.roll(1, dims=-1) * sin, key * cos - key.roll(1, dims=-1) * sin


def _cpu_attention(query, key, value, attention_mask, query_length, **kwargs):
    mask_term = attention_mask.to(query.dtype).unsqueeze(-1).unsqueeze(-1)
    scale = query.new_tensor(sum((index % 5) + 1 for index in range(query_length))) / (query_length + 3)
    return query + key * scale + value.roll(1, dims=1) - mask_term / (query_length + 1)


class GeneratedAttention(nn.Module):
    def __init__(self, rng):
        super().__init__()
        self.num_heads = 4
        self.num_key_value_heads = 2
        self.num_key_value_groups = self.num_heads // self.num_key_value_heads
        self.head_dim = 2
        self.hidden_size = self.num_heads * self.head_dim
        self.attention_dropout = rng.randrange(1, 4) / 20
        self.config = SimpleNamespace(group_size_ratio=1 / 4)
        self.q_proj = _seeded_linear(rng, self.hidden_size, self.hidden_size)
        self.k_proj = _seeded_linear(rng, self.hidden_size, self.num_key_value_heads * self.head_dim)
        self.v_proj = _seeded_linear(rng, self.hidden_size, self.num_key_value_heads * self.head_dim)
        self.o_proj = _seeded_linear(rng, self.hidden_size, self.hidden_size)
        self.is_causal = True
        self.sliding_window = None
        self._flash_attn_uses_top_left_mask = False


setattr(
    GeneratedAttention,
    "forward",
    getattr(longlora_module, "_".join(("llama", "flash", "attention", "2", "forward"))),
)


class AttentionPipeline(nn.Module):
    def __init__(self, rng):
        super().__init__()
        self.block = GeneratedAttention(rng)

    def forward(self, hidden_states, attention_mask):
        seq_len = hidden_states.size(1)
        phase = hidden_states.cumsum(dim=1).mean(dim=-1, keepdim=True)
        cos = torch.cos(phase).unsqueeze(1).expand(-1, 1, -1, self.block.head_dim)
        sin = torch.sin(phase).unsqueeze(1).expand_as(cos)
        return self.block(
            hidden_states,
            attention_mask=attention_mask,
            position_embeddings=(cos, sin),
            output_attentions=True,
        )


class TestGeneratedFlashAttentionState(unittest.TestCase):
    def test_shifted_attention_through_pipeline(self):
        rng = random.Random(sum((index + 3) * ord(char) for index, char in enumerate(self.id())))
        torch.set_printoptions(precision=5, linewidth=240, sci_mode=False)

        seq_len = sum((index % 3) + 1 for index in range(8))
        features = [
            (rng.uniform(-1.0, 1.0) + ((row * column) % 7) / 9)
            for row in range(seq_len)
            for column in range(8)
        ]
        hidden_states = torch.tensor(features, dtype=torch.float32).reshape(1, seq_len, 8)
        attention_mask = torch.tensor(
            [[(rng.randrange(0, 7) + index * index) % 5 for index in range(seq_len)]],
            dtype=torch.float32,
        )
        pipeline = AttentionPipeline(rng)
        pipeline.train()

        with (
            patch.object(longlora_module, "apply_rotary_pos_emb", side_effect=_rotary_mix),
            patch.object(longlora_module, "is_transformers_version_greater_than", return_value=True),
            patch(
                "transformers.modeling_flash_attention_utils._flash_attention_forward",
                side_effect=_cpu_attention,
            ),
        ):
            output, weights, cache = pipeline(hidden_states, attention_mask)

        self.assertEqual(output.shape, hidden_states.shape)
        self.assertTrue(torch.isfinite(output).all())
        self.assertIsNone(weights)
        self.assertIsNone(cache)
        self.assertGreater(output.square().mean().item(), 0)
