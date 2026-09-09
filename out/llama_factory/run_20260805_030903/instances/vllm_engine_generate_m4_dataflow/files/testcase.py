import asyncio
import random
import unittest
from types import SimpleNamespace

import llamafactory.chat.vllm_engine as vllm_module
from llamafactory.chat.vllm_engine import VllmEngine
from llamafactory.extras.constants import AUDIO_PLACEHOLDER, IMAGE_PLACEHOLDER, VIDEO_PLACEHOLDER


class _SamplingParamsHarness:
    def __init__(self, **kwargs):
        self.options = kwargs


class _MultimodalHarness:
    def process_messages(self, messages, images, videos, audios, processor):
        salt = len(images) * 3 + len(videos) * 5 + len(audios) * 7
        return [
            {
                "role": message["role"],
                "content": message["content"] + chr(ord("a") + (salt + index) % 26),
            }
            for index, message in enumerate(messages)
        ]

    def _regularize_images(self, images, **kwargs):
        return {"images": [(index, len(repr(item))) for index, item in enumerate(images)]}

    def _regularize_videos(self, videos, **kwargs):
        return {"videos": [(index * index, len(repr(item))) for index, item in enumerate(videos)]}

    def _regularize_audios(self, audios, **kwargs):
        return {
            "audios": [sum(ord(char) for char in repr(item)) % 997 for item in audios],
            "sampling_rates": [8000 + index * 137 for index, _ in enumerate(audios)],
        }


class _TemplateHarness:
    def __init__(self):
        self.mm_plugin = _MultimodalHarness()

    def encode_oneturn(self, tokenizer, messages, system, tools):
        text = "|".join(message["content"] for message in messages)
        salt = sum(ord(char) for char in (system or "") + (tools or ""))
        return [((ord(char) + salt + index * index) % 89) + 3 for index, char in enumerate(text)], None

    def get_stop_token_ids(self, tokenizer):
        return [2, 7]


class _ModelHarness:
    def __init__(self):
        self.calls = []

    def generate(self, request, sampling_params, request_id, lora_request):
        self.calls.append((request, sampling_params, request_id, lora_request))
        prompt_ids = request["prompt_token_ids"]
        checksum = sum((index + 1) * token for index, token in enumerate(prompt_ids))

        async def output_stream():
            text = ""
            for step in range(3):
                text += chr(ord("a") + (checksum + step * step) % 26)
                yield SimpleNamespace(
                    outputs=[
                        SimpleNamespace(
                            text=text,
                            token_ids=[(checksum + offset * offset) % 101 for offset in range(step + 1)],
                            finish_reason="stop" if step == 2 else None,
                        )
                    ],
                    prompt_token_ids=prompt_ids,
                )

        return output_stream()


class TestVllmEngineGenerateDataFlow(unittest.TestCase):
    def test_seeded_branch_matrix_through_chat(self):
        rng = random.Random(sum((index + 5) * ord(char) for index, char in enumerate(self.id())))
        vllm_module.SamplingParams = _SamplingParamsHarness

        engine = VllmEngine.__new__(VllmEngine)
        engine.template = _TemplateHarness()
        engine.tokenizer = SimpleNamespace()
        engine.processor = SimpleNamespace()
        engine.model = _ModelHarness()
        engine.model_args = SimpleNamespace(
            image_max_pixels=4096,
            image_min_pixels=64,
            video_max_pixels=2048,
            video_min_pixels=32,
            video_fps=2.5,
            video_maxlen=48,
            audio_sampling_rate=16000,
        )
        engine.lora_request = None

        async def run_matrix():
            responses = []
            for scenario in range(20):
                fragments = [
                    chr(ord("a") + (rng.randrange(26) + scenario * position + position * position) % 26)
                    for position in range(23 + scenario % 7)
                ]
                content = "".join(fragments)
                modality = scenario % 4
                images = [f"image-{scenario}-{index}-{rng.randrange(10000)}" for index in range(1 + scenario % 3)]
                videos = [f"video-{scenario}-{index}-{rng.randrange(10000)}" for index in range(1 + scenario % 2)]
                audios = [f"audio-{scenario}-{index}-{rng.randrange(10000)}" for index in range(1 + scenario % 4)]
                if modality != 0:
                    images = None
                if modality != 1:
                    videos = None
                if modality != 2:
                    audios = None

                if scenario % 6 == 1 and images:
                    content = IMAGE_PLACEHOLDER + content
                elif scenario % 6 == 2 and videos:
                    content = VIDEO_PLACEHOLDER + content
                elif scenario % 6 == 3 and audios:
                    content = AUDIO_PLACEHOLDER + content

                messages = [
                    {"role": "user", "content": content},
                    {"role": "user", "content": content[::-1] + chr(ord("a") + scenario)},
                ]
                generation_mode = scenario % 5
                if generation_mode == 0:
                    engine.generating_args = {
                        "default_system": "system-" + str(rng.randrange(100000)),
                        "max_new_tokens": 9 + rng.randrange(8),
                        "repetition_penalty": 1.0,
                        "temperature": 0.6,
                        "top_p": 0.9,
                        "top_k": 40,
                        "skip_special_tokens": True,
                    }
                    options = {}
                else:
                    prompt_bound = 11 + (scenario % 3) * 80
                    engine.generating_args = {
                        "default_system": "system-" + str(rng.randrange(100000)),
                        "max_length": prompt_bound,
                        "repetition_penalty": 1.0,
                        "temperature": 0.6,
                        "top_p": 0.9,
                        "top_k": 40,
                        "skip_special_tokens": True,
                    }
                    if generation_mode == 1:
                        options = {}
                    elif generation_mode == 2:
                        options = {"max_length": 13 + scenario * 17}
                    elif generation_mode == 3:
                        options = {"max_new_tokens": 5 + scenario}
                    else:
                        options = {
                            "max_length": 31 + scenario * 19,
                            "max_new_tokens": 7 + scenario,
                            "temperature": (rng.randrange(70) + 1) / 100,
                        }

                responses.append(
                    await engine.chat(
                        messages,
                        system=None if scenario % 3 else "override-" + str(rng.randrange(100000)),
                        tools="tool-" + str(sum(ord(char) for char in fragments) % 997),
                        images=images,
                        videos=videos,
                        audios=audios,
                        **options,
                    )
                )
            return responses

        responses = asyncio.run(run_matrix())
        self.assertEqual(len(responses), len(engine.model.calls))
        self.assertTrue(all(len(group) == 1 for group in responses))
        self.assertTrue(all(group[0].finish_reason == "stop" for group in responses))
        self.assertGreater(len({group[0].prompt_length for group in responses}), 3)
