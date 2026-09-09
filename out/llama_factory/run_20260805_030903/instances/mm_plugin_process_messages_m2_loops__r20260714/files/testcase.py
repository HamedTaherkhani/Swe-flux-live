import unittest
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from llamafactory.data.mm_plugin import MiniCPMVPlugin
from llamafactory.extras.constants import AUDIO_PLACEHOLDER, IMAGE_PLACEHOLDER


class DummyImageProcessor:
    def __init__(self) -> None:
        self.max_slice_nums = 4
        self.use_image_id = True

    def get_slice_image_placeholder(self, image_size, idx, max_slice_nums, use_image_id):
        return f"<slice:{idx}:{image_size[0]}x{image_size[1]}:{max_slice_nums}:{int(use_image_id)}>"


class DummyProcessor:
    def __init__(self) -> None:
        self.image_processor = DummyImageProcessor()
        self.feature_extractor = object()


class TestMiniCPMVProcessMessagesM2Loops(unittest.TestCase):
    def test_nested_loop_iteration_map_across_invocations(self):
        plugin = MiniCPMVPlugin(image_token="<IMG>", video_token=None, audio_token="<AUD>", expand_mm_tokens=True)
        processor = DummyProcessor()

        def build_message(prefix: str, image_count: int, audio_count: int):
            image_part = " ".join([IMAGE_PLACEHOLDER] * image_count)
            audio_part = " ".join([AUDIO_PLACEHOLDER] * audio_count)
            return {"role": "user", "content": f"{prefix} {image_part} {audio_part}".strip()}

        scenarios = [
            {
                "messages": [
                    build_message("INV1_M1", image_count=0, audio_count=5),
                    build_message("INV1_M2", image_count=1, audio_count=4),
                    build_message("INV1_M3", image_count=2, audio_count=3),
                    build_message("INV1_M4", image_count=3, audio_count=2),
                    build_message("INV1_M5", image_count=4, audio_count=1),
                    build_message("INV1_M6", image_count=5, audio_count=0),
                ],
                "image_count": 15,
                "audio_count": 15,
            },
            {
                "messages": [
                    build_message("INV2_M1", image_count=2, audio_count=1),
                    build_message("INV2_M2", image_count=0, audio_count=3),
                    build_message("INV2_M3", image_count=3, audio_count=0),
                    build_message("INV2_M4", image_count=1, audio_count=2),
                    build_message("INV2_M5", image_count=4, audio_count=4),
                ],
                "image_count": 10,
                "audio_count": 10,
            },
        ]

        expected_calls = []
        for scenario in scenarios:
            expected_calls.append(("image", scenario["image_count"]))
            expected_calls.append(("audio", scenario["audio_count"]))

        call_index = {"value": 0}

        def fake_get_mm_inputs(images, videos, audios, current_processor, **kwargs):
            del videos, current_processor
            if call_index["value"] >= len(expected_calls):
                raise AssertionError("Unexpected extra _get_mm_inputs invocation.")

            expected_kind, expected_count = expected_calls[call_index["value"]]
            call_index["value"] += 1

            if expected_kind == "image":
                assert len(images) == expected_count, "Image count mismatch in mocked _get_mm_inputs."
                assert len(audios) == 0, "Unexpected audio payload in image branch."
                image_sizes = [[(100 + i, 200 + i) for i in range(expected_count)]]
                return {"image_sizes": image_sizes}

            assert len(images) == 0, "Unexpected image payload in audio branch."
            assert len(audios) == expected_count, "Audio count mismatch in mocked _get_mm_inputs."
            assert kwargs.get("ret_phs") is True, "Audio branch must request placeholders."
            audio_placeholders = [[f"<audio_ph:{i}>" for i in range(expected_count)]]
            return {"audio_phs": audio_placeholders}

        plugin._get_mm_inputs = fake_get_mm_inputs

        for scenario in scenarios:
            messages = deepcopy(scenario["messages"])
            images = [object() for _ in range(scenario["image_count"])]
            audios = [object() for _ in range(scenario["audio_count"])]

            result = plugin.process_messages(
                messages=messages,
                images=images,
                videos=[],
                audios=audios,
                processor=processor,
            )

            self.assertEqual(len(result), len(messages))
            joined_content = " ".join(message["content"] for message in result)
            for message in result:
                content = message["content"]
                self.assertNotIn(IMAGE_PLACEHOLDER, content)
                self.assertNotIn(AUDIO_PLACEHOLDER, content)
                self.assertNotIn("(<image>./</image>)", content)
                self.assertNotIn("(<audio>./</audio>)", content)

            self.assertIn("<slice:", joined_content)
            self.assertIn("<audio_ph:", joined_content)

        self.assertEqual(call_index["value"], len(expected_calls))
