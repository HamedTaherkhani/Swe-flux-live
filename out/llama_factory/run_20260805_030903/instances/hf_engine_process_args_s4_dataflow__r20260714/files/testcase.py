import unittest

import torch

from src.llamafactory.chat.hf_engine import HuggingfaceEngine
from src.llamafactory.extras.constants import AUDIO_PLACEHOLDER, IMAGE_PLACEHOLDER, VIDEO_PLACEHOLDER


class _DummyConfig:
    def __init__(self, model_type=None):
        self.model_type = model_type


class _DummyModel:
    def __init__(self, model_type=None):
        self.device = torch.device("cpu")
        self.dtype = torch.float32
        self.config = _DummyConfig(model_type=model_type)


class _DummyTokenizer:
    pad_token_id = 0


class _DummyMMPlugin:
    def __init__(self):
        self.call_count = 0
        self.observed_message_starts = []

    def process_messages(self, messages, images, videos, audios, processor):
        del images, videos, audios, processor
        self.observed_message_starts.append(messages[0]["content"])
        return messages

    def process_token_ids(self, prompt_ids, labels, images, videos, audios, tokenizer, processor):
        del labels, images, videos, audios, tokenizer, processor
        return prompt_ids + [99], None

    def get_mm_inputs(self, **kwargs):
        del kwargs
        if self.call_count == 0:
            self.call_count += 1
            return {
                "pixel_values": [torch.tensor([1.0, 2.0]), torch.tensor([3.0, 4.0])],
                "second_per_grid_ts": torch.tensor([0.5, 1.5], dtype=torch.float32),
                "image_sizes": [[8, 8], [16, 16]],
            }

        if self.call_count == 1:
            self.call_count += 1
            return {
                "video_embeds": [
                    [torch.tensor([1, 2]), torch.tensor([3, 4])],
                    [torch.tensor([5, 6]), torch.tensor([7, 8])],
                ],
                "token_type_ids": [1, 1, 2, 2],
                "audio_feature_lens": torch.tensor([2, 4], dtype=torch.int64),
                "second_per_grid_ts": torch.tensor([0.25], dtype=torch.float32),
                "image_sizes": torch.tensor([[32, 32]], dtype=torch.int64),
            }

        raise AssertionError("Unexpected extra invocation of get_mm_inputs.")


class _DummyTemplate:
    def __init__(self, mm_plugin):
        self.mm_plugin = mm_plugin

    def encode_oneturn(self, tokenizer, paired_messages, system, tools):
        del tokenizer, paired_messages, tools
        if system is None:
            raise AssertionError("System should always be resolved before encode_oneturn.")
        return [11, 22, 33], None

    def get_stop_token_ids(self, tokenizer):
        del tokenizer
        return [2, 3]


class TestHuggingfaceEngineProcessArgsDataFlow(unittest.TestCase):
    def test_multibranch_reaching_defs(self):
        plugin = _DummyMMPlugin()
        template = _DummyTemplate(plugin)
        tokenizer = _DummyTokenizer()

        base_generating_args = {
            "default_system": "fallback-system",
            "do_sample": False,
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 50,
            "repetition_penalty": 1.0,
            "length_penalty": 1.0,
            "skip_special_tokens": True,
        }

        messages1 = [{"role": "user", "content": "hello"}]
        input_kwargs1 = {
            "num_return_sequences": 2,
            "temperature": 0.0,
            "max_new_tokens": 6,
            "stop": "unused-stop-seq",
        }
        gen_kwargs1, prompt_length1 = HuggingfaceEngine._process_args(
            model=_DummyModel(model_type=None),
            tokenizer=tokenizer,
            processor=object(),
            template=template,
            generating_args=base_generating_args.copy(),
            messages=messages1,
            system=None,
            tools="tool-a",
            images=[object(), object()],
            videos=[object()],
            audios=[object()],
            input_kwargs=input_kwargs1,
        )

        self.assertEqual(prompt_length1, 4)
        self.assertTrue(gen_kwargs1["generation_config"].do_sample)
        self.assertEqual(gen_kwargs1["generation_config"].temperature, 1.0)
        self.assertEqual(gen_kwargs1["generation_config"].num_return_sequences, 2)
        self.assertIsInstance(gen_kwargs1["second_per_grid_ts"], list)
        self.assertEqual(input_kwargs1, {})
        self.assertTrue(
            plugin.observed_message_starts[0].startswith(
                AUDIO_PLACEHOLDER + VIDEO_PLACEHOLDER + (IMAGE_PLACEHOLDER * 2)
            )
        )

        messages2 = [
            {
                "role": "user",
                "content": IMAGE_PLACEHOLDER + VIDEO_PLACEHOLDER + AUDIO_PLACEHOLDER + " second",
            }
        ]
        input_kwargs2 = {
            "do_sample": False,
            "max_length": 18,
            "max_new_tokens": 3,
        }
        gen_kwargs2, prompt_length2 = HuggingfaceEngine._process_args(
            model=_DummyModel(model_type="minicpmv"),
            tokenizer=tokenizer,
            processor=object(),
            template=template,
            generating_args=base_generating_args.copy(),
            messages=messages2,
            system="explicit-system",
            tools="tool-b",
            images=[object()],
            videos=[object()],
            audios=[object()],
            input_kwargs=input_kwargs2,
        )

        self.assertEqual(prompt_length2, 4)
        self.assertFalse(gen_kwargs2["generation_config"].do_sample)
        self.assertEqual(gen_kwargs2["generation_config"].max_new_tokens, 3)
        self.assertIn("input_ids", gen_kwargs2)
        self.assertIn("tokenizer", gen_kwargs2)
        self.assertIn("audio_feature_lens", gen_kwargs2)
        self.assertNotIn("image_sizes", gen_kwargs2)
        self.assertEqual(input_kwargs2, {})
        self.assertEqual(plugin.call_count, 2)
        self.assertTrue(plugin.observed_message_starts[1].endswith(" second"))
