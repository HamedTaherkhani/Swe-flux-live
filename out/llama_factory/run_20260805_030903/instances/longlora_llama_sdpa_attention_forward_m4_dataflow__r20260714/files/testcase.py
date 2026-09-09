import types
import unittest
from unittest import mock

import torch
import torch.nn as nn

from src.llamafactory.model.model_utils import longlora


class _DummyCache:
    def __init__(self) -> None:
        self.calls = 0

    def update(self, key_states, value_states, layer_idx, cache_kwargs):
        del layer_idx, cache_kwargs
        self.calls += 1
        return key_states + 0.125, value_states - 0.25


class _DummySdpaAttention(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        hidden_size = 8
        self.num_heads = 4
        self.num_key_value_heads = 4
        self.num_key_value_groups = 1
        self.head_dim = hidden_size // self.num_heads
        self.hidden_size = hidden_size
        self.attention_dropout = 0.0
        self.layer_idx = 0
        self.config = types.SimpleNamespace(group_size_ratio=0.5)

        self.q_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        self.k_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        self.v_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        self.o_proj = nn.Linear(hidden_size, hidden_size, bias=False)

    def rotary_emb(self, value_states, position_ids):
        del value_states, position_ids
        cos = torch.ones((1, 1, 1, self.head_dim), dtype=torch.float32)
        sin = torch.zeros((1, 1, 1, self.head_dim), dtype=torch.float32)
        return cos, sin


class TestLongLoraSdpaAttentionForwardM4(unittest.TestCase):
    def test_branch_sensitive_dataflow_across_invocations(self):
        torch.manual_seed(7)
        module = _DummySdpaAttention()
        hidden_states = torch.arange(32, dtype=torch.float32).reshape(1, 4, 8) / 10.0
        position_ids = torch.tensor([[0, 1, 2, 3]], dtype=torch.long)
        attention_mask = torch.zeros((1, 1, 4, 4), dtype=torch.float32)
        attention_mask[:, :, 0, 3] = -5.0
        position_embeddings = (
            torch.ones((1, 1, 1, module.head_dim), dtype=torch.float32),
            torch.zeros((1, 1, 1, module.head_dim), dtype=torch.float32),
        )

        with mock.patch.object(longlora, "apply_rotary_pos_emb", side_effect=lambda q, k, c, s: (q, k)):
            with mock.patch.object(longlora, "repeat_kv", side_effect=lambda x, g: x):
                module.eval()
                output1, attn1, cache1 = longlora.llama_sdpa_attention_forward(
                    module,
                    hidden_states=hidden_states,
                    attention_mask=None,
                    position_ids=position_ids,
                    past_key_value=None,
                    output_attentions=False,
                    cache_position=None,
                    position_embeddings=None,
                )

                module.train()
                cache = _DummyCache()
                output2, attn2, cache2 = longlora.llama_sdpa_attention_forward(
                    module,
                    hidden_states=hidden_states,
                    attention_mask=attention_mask.clone(),
                    position_ids=position_ids,
                    past_key_value=cache,
                    output_attentions=False,
                    cache_position=torch.tensor([0, 1, 2, 3], dtype=torch.long),
                    position_embeddings=position_embeddings,
                )

                output3, attn3, cache3 = longlora.llama_sdpa_attention_forward(
                    module,
                    hidden_states=hidden_states,
                    attention_mask=None,
                    position_ids=position_ids,
                    past_key_value=None,
                    output_attentions=False,
                    cache_position=None,
                    position_embeddings=None,
                )

        self.assertEqual(output1.shape, (1, 4, 8))
        self.assertEqual(output2.shape, (1, 4, 8))
        self.assertEqual(output3.shape, (1, 4, 8))
        self.assertIsNone(attn1)
        self.assertIsNone(attn2)
        self.assertIsNone(attn3)
        self.assertIsNone(cache1)
        self.assertIs(cache2, cache)
        self.assertIsNone(cache3)
        self.assertEqual(cache.calls, 1)
        self.assertTrue(torch.isfinite(output1).all())
        self.assertTrue(torch.isfinite(output2).all())
        self.assertTrue(torch.isfinite(output3).all())
        self.assertFalse(torch.allclose(output1, output2))
        self.assertFalse(torch.allclose(output2, output3))
