import unittest
from copy import deepcopy

import torch

from llamafactory.data.mm_plugin import Qwen2OmniPlugin
from llamafactory.extras.constants import AUDIO_PLACEHOLDER, IMAGE_PLACEHOLDER, VIDEO_PLACEHOLDER


class IntIndexMessage(dict):
    """Dict message that also supports integer indexing used by buggy code path."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return dict.__getitem__(self, "content")
        return dict.__getitem__(self, key)


class DummyImageProcessor:
    def __init__(self, merge_size: int = 2) -> None:
        self.merge_size = merge_size


class DummyProcessor:
    def __init__(self) -> None:
        self.image_processor = DummyImageProcessor(merge_size=2)
        self.feature_extractor = object()
        self.use_audio_in_video = True

    def get_chunked_index(self, indices, chunk_size):
        del chunk_size
        n = int(indices.numel())
        return [(start, min(start + 8, n)) for start in range(0, n, 8)]


class TestQwen2OmniProcessMessagesLoops(unittest.TestCase):
    def test_audio_video_chunk_loop_iterations(self):
        plugin = Qwen2OmniPlugin(image_token="<IMG>", video_token="<VID>", audio_token="<AUD>")
        plugin.image_processor = DummyImageProcessor(merge_size=2)

        def audio_chunked_index(indices, chunk_size):
            del chunk_size
            n = int(indices.numel())
            return [(start, min(start + 2, n)) for start in range(0, n, 2)]

        plugin.get_chunked_index = audio_chunked_index
        processor = DummyProcessor()

        scenarios = [
            {
                "feature_attention_mask": torch.ones((1, 21), dtype=torch.int64),
                "video_grid_thw": [torch.tensor([6, 4, 4], dtype=torch.int64)],
                "video_second_per_grid": torch.tensor([0.5], dtype=torch.float32),
            },
            {
                "feature_attention_mask": torch.ones((1, 13), dtype=torch.int64),
                "video_grid_thw": [torch.tensor([4, 4, 4], dtype=torch.int64)],
                "video_second_per_grid": torch.tensor([0.5], dtype=torch.float32),
            },
        ]
        call_counter = {"count": 0}

        def fake_get_mm_inputs(images, videos, audios, current_processor):
            del images, videos, audios, current_processor
            idx = call_counter["count"]
            call_counter["count"] += 1
            if idx >= len(scenarios):
                raise AssertionError("Unexpected extra _get_mm_inputs invocation.")
            return scenarios[idx]

        plugin._get_mm_inputs = fake_get_mm_inputs

        base_messages = [IntIndexMessage(role="user", content=f"{VIDEO_PLACEHOLDER} scene {AUDIO_PLACEHOLDER} end")]
        for _ in range(2):
            result = plugin.process_messages(
                messages=deepcopy(base_messages),
                images=[],
                videos=[object()],
                audios=[object()],
                processor=processor,
            )
            self.assertEqual(len(result), 1)
            content = result[0]["content"]
            self.assertNotIn(IMAGE_PLACEHOLDER, content)
            self.assertNotIn(VIDEO_PLACEHOLDER, content)
            self.assertNotIn(AUDIO_PLACEHOLDER, content)
            self.assertIn("<|vision_bos|>", content)
            self.assertIn("<|audio_bos|>", content)
            self.assertIn("<|audio_eos|>", content)
            self.assertIn("<|vision_eos|>", content)

        self.assertEqual(call_counter["count"], 2)

