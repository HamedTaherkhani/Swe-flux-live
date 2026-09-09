import random
import types
import unittest
from types import SimpleNamespace

import torch

from llamafactory.data.mm_plugin import IMAGE_PLACEHOLDER, get_mm_plugin
from llamafactory.data.processor.supervised import SupervisedDatasetProcessor


class _TemplateHarness:
    def __init__(self, plugin):
        self.mm_plugin = plugin
        self.efficient_eos = False

    def encode_multiturn(self, tokenizer, messages, system, tools):
        source = [len(messages[0]["content"]) % ord("a") + 1]
        target = [len(messages[-1]["content"]) % ord("Y") + 2]
        return [(source, target)]


class TestQwen2OmniLoopBehavior(unittest.TestCase):
    def test_seeded_image_expansion_through_dataset_processor(self):
        rng = random.Random(sum((index + 1) * ord(char) for index, char in enumerate("perturb-alpha-combo")))
        multiplicities = [1 + rng.randrange(7) for _ in range(ord("W"))]
        content = "|".join(
            f"segment-{index}:"
            + IMAGE_PLACEHOLDER * multiplicity
            + ("<video>" if index % 4 == 0 else "")
            + ("<audio>" if index % 5 == 1 else "")
            for index, multiplicity in enumerate(multiplicities)
        )
        images = [object() for _ in range(sum(multiplicities) + 10)]

        plugin = get_mm_plugin(
            name="qwen2_omni",
            image_token="<|IMAGE|>",
            video_token="<|VIDEO|>",
            audio_token="<|AUDIO|>",
        )

        def _fake_mm_inputs(self, images, videos, audios, processor):
            grids = [
                torch.tensor([1 + index % 7, 3 + index % 5, 4 + (index * 3) % 11])
                for index in range(len(images))
            ]
            return {
                "image_grid_thw": torch.stack(grids),
                "video_grid_thw": torch.stack(
                    [torch.tensor([2 + index % 4, 4 + index % 3, 6 + index % 5]) for index in range(len(videos))]
                ),
                "feature_attention_mask": torch.full((len(audios), 24), 1, dtype=torch.int64),
            }

        plugin._get_mm_inputs = types.MethodType(_fake_mm_inputs, plugin)
        template = _TemplateHarness(plugin)
        tokenizer = SimpleNamespace(eos_token_id=0)
        processor = SimpleNamespace(
            image_processor=SimpleNamespace(merge_size=3),
            video_processor=object(),
            feature_extractor=object(),
            use_audio_in_video=False,
        )
        data_args = SimpleNamespace(mask_history=False, cutoff_len=ord("z"), train_on_prompt=False)
        dataset_processor = SupervisedDatasetProcessor(template, tokenizer, processor, data_args)
        examples = {
            "_prompt": [[{"role": "user", "content": content}]],
            "_response": [[{"role": "assistant", "content": "Summarize the transformed stream." + IMAGE_PLACEHOLDER * 10}]],
            "_system": [None],
            "_tools": [None],
            "_images": [images],
            "_videos": [[object() for _ in range(22)]],
            "_audios": [[object() for _ in range(18)]],
        }

        result = dataset_processor.preprocess_dataset(examples)

        self.assertEqual(set(result), {"attention_mask", "audios", "images", "input_ids", "labels", "videos"})
        self.assertEqual(len(result["input_ids"]), len(result["labels"]))
        self.assertTrue(all(value == 1 for value in result["attention_mask"][0]))
        self.assertIs(result["images"][0], images)