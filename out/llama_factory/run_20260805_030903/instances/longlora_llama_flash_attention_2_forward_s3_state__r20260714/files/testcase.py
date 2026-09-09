import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch
import torch.nn as nn


ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from llamafactory.model.model_utils import longlora


def _fill_linear(linear: nn.Linear, start: float) -> None:
    total = linear.weight.numel()
    values = torch.linspace(start, start + (total - 1) * 0.01, steps=total, dtype=torch.float32)
    with torch.no_grad():
        linear.weight.copy_(values.reshape_as(linear.weight))


class _DummyFlashAttentionModule:
    def __init__(self) -> None:
        self.num_heads = 4
        self.num_key_value_heads = 2
        self.num_key_value_groups = self.num_heads // self.num_key_value_heads
        self.head_dim = 2
        self.hidden_size = self.num_heads * self.head_dim
        self.attention_dropout = 0.25
        self.training = True
        self.config = SimpleNamespace(group_size_ratio=0.5, _pre_quantization_dtype=torch.float32)
        self.layer_idx = 0
        self.sliding_window = None
        self._flash_attn_uses_top_left_mask = False
        self.is_causal = True
        self.last_attention_mask = None

        self.q_proj = nn.Linear(self.hidden_size, self.num_heads * self.head_dim, bias=False)
        self.k_proj = nn.Linear(self.hidden_size, self.num_key_value_heads * self.head_dim, bias=False)
        self.v_proj = nn.Linear(self.hidden_size, self.num_key_value_heads * self.head_dim, bias=False)
        self.o_proj = nn.Linear(self.hidden_size, self.hidden_size, bias=False)

        _fill_linear(self.q_proj, 0.01)
        _fill_linear(self.k_proj, 0.11)
        _fill_linear(self.v_proj, 0.21)
        with torch.no_grad():
            self.o_proj.weight.copy_(torch.eye(self.hidden_size, dtype=torch.float32))

    def rotary_emb(self, value_states: torch.Tensor, position_ids: torch.LongTensor):
        del value_states, position_ids
        return torch.zeros(1, dtype=torch.float32), torch.zeros(1, dtype=torch.float32)

    def _flash_attention_forward(
        self,
        query_states: torch.Tensor,
        key_states: torch.Tensor,
        value_states: torch.Tensor,
        attention_mask: torch.Tensor,
        q_len: int,
        dropout: float = 0.0,
    ) -> torch.Tensor:
        del q_len, dropout
        self.last_attention_mask = attention_mask.detach().clone()
        return query_states + key_states + value_states


class TestLongLoraFlashAttention2ForwardState(unittest.TestCase):
    def test_shift_mask_and_dtype_branch_state(self) -> None:
        torch.manual_seed(2026)
        module = _DummyFlashAttentionModule()
        hidden_states = torch.arange(32, dtype=torch.float32).reshape(1, 4, 8) / 10.0
        attention_mask = torch.tensor([[11, 13, 17, 19]], dtype=torch.int64)
        position_ids = torch.arange(4, dtype=torch.long).unsqueeze(0)

        with (
            patch.object(longlora, "apply_rotary_pos_emb", side_effect=lambda q, k, c, s: (q, k)),
            patch.object(
                longlora,
                "repeat_kv",
                side_effect=lambda state, num_groups: state.repeat_interleave(num_groups, dim=1),
            ),
            patch.object(longlora, "is_transformers_version_greater_than", return_value=False),
        ):
            attn_output, attn_weights, past_key_value = longlora.llama_flash_attention_2_forward(
                module,
                hidden_states=hidden_states,
                attention_mask=attention_mask,
                position_ids=position_ids,
                output_attentions=True,
            )

        self.assertEqual(attn_output.shape, (1, 4, 8))
        self.assertTrue(torch.isfinite(attn_output).all().item())
        self.assertIsNone(attn_weights)
        self.assertIsNone(past_key_value)
        self.assertTrue(
            torch.equal(module.last_attention_mask, torch.tensor([[11, 13], [11, 13]], dtype=torch.int64))
        )


if __name__ == "__main__":
    unittest.main()
