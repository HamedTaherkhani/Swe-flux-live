import asyncio
import unittest
from types import SimpleNamespace

from src.llamafactory.chat import vllm_engine as vllm_mod


class FakeSamplingParams:
    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)


class DummyMMPlugin:
    def process_messages(self, messages, images, videos, audios, processor):
        return [{"role": item["role"], "content": item["content"]} for item in messages]

    def _regularize_images(self, images, image_max_pixels, image_min_pixels):
        return {"images": [f"img-{idx}" for idx, _ in enumerate(images)]}

    def _regularize_videos(self, videos, image_max_pixels, image_min_pixels, video_fps, video_maxlen):
        return {"videos": [f"vid-{idx}" for idx, _ in enumerate(videos)]}

    def _regularize_audios(self, audios, sampling_rate):
        return {
            "audios": [f"aud-{idx}" for idx, _ in enumerate(audios)],
            "sampling_rates": [sampling_rate for _ in audios],
        }


class DummyTemplate:
    def __init__(self):
        self.mm_plugin = DummyMMPlugin()

    def encode_oneturn(self, tokenizer, paired_messages, system, tools):
        return [101, 102, 103], None

    def get_stop_token_ids(self, tokenizer):
        return [0, 1]


class DummyModel:
    def __init__(self):
        self.calls = []

    def generate(self, prompt_dict, sampling_params, request_id, lora_request):
        call = {
            "prompt_dict": prompt_dict,
            "sampling_params": sampling_params,
            "request_id": request_id,
            "lora_request": lora_request,
        }
        self.calls.append(call)
        return {"kind": "dummy_generator", "call_index": len(self.calls)}


def build_engine(generating_args):
    engine = object.__new__(vllm_mod.VllmEngine)
    engine.template = DummyTemplate()
    engine.tokenizer = object()
    engine.processor = object()
    engine.generating_args = dict(generating_args)
    engine.model = DummyModel()
    engine.model_args = SimpleNamespace(
        image_max_pixels=1024,
        image_min_pixels=16,
        video_max_pixels=2048,
        video_min_pixels=32,
        video_fps=4,
        video_maxlen=8,
        audio_sampling_rate=16000,
    )
    engine.lora_request = None
    return engine


class TestVllmEngineGenerateM4DataFlow(unittest.TestCase):
    async def _invoke(self, engine, **kwargs):
        messages = [{"role": "user", "content": "hello"}]
        return await engine._generate(messages=messages, system=None, tools=None, **kwargs)

    def test_branch_sensitive_dataflow(self):
        vllm_mod.SamplingParams = FakeSamplingParams

        engine_with_max_new_tokens = build_engine(
            {
                "default_system": "sys-a",
                "max_new_tokens": 9,
                "max_length": 128,
                "repetition_penalty": 1.05,
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 8,
                "skip_special_tokens": True,
            }
        )
        engine_without_max_new_tokens_small = build_engine(
            {
                "default_system": "sys-b",
                "max_length": 2,
                "repetition_penalty": 1.1,
                "temperature": 0.6,
                "top_p": 0.85,
                "top_k": 4,
                "skip_special_tokens": True,
            }
        )
        engine_without_max_new_tokens_large = build_engine(
            {
                "default_system": "sys-c",
                "max_length": 8,
                "repetition_penalty": 1.15,
                "temperature": 0.65,
                "top_p": 0.88,
                "top_k": 6,
                "skip_special_tokens": False,
            }
        )

        asyncio.run(self._invoke(engine_with_max_new_tokens, images=["img-a", "img-b"]))
        asyncio.run(self._invoke(engine_with_max_new_tokens, videos=["vid-a"], max_length=12))
        asyncio.run(
            self._invoke(
                engine_with_max_new_tokens,
                audios=["aud-a", "aud-b"],
                max_length=10,
                max_new_tokens=4,
            )
        )
        asyncio.run(self._invoke(engine_without_max_new_tokens_small))
        asyncio.run(self._invoke(engine_without_max_new_tokens_large))

        all_calls = (
            engine_with_max_new_tokens.model.calls
            + engine_without_max_new_tokens_small.model.calls
            + engine_without_max_new_tokens_large.model.calls
        )
        self.assertEqual(len(all_calls), 5)

        self.assertEqual(all_calls[0]["sampling_params"].kwargs["max_tokens"], 9)
        self.assertEqual(all_calls[1]["sampling_params"].kwargs["max_tokens"], 9)
        self.assertEqual(all_calls[2]["sampling_params"].kwargs["max_tokens"], 4)
        self.assertEqual(all_calls[3]["sampling_params"].kwargs["max_tokens"], 1)
        self.assertEqual(all_calls[4]["sampling_params"].kwargs["max_tokens"], 5)

        self.assertIn("image", all_calls[0]["prompt_dict"]["multi_modal_data"])
        self.assertIn("video", all_calls[1]["prompt_dict"]["multi_modal_data"])
        self.assertIn("audio", all_calls[2]["prompt_dict"]["multi_modal_data"])
        self.assertIsNone(all_calls[3]["prompt_dict"]["multi_modal_data"])
        self.assertIsNone(all_calls[4]["prompt_dict"]["multi_modal_data"])
