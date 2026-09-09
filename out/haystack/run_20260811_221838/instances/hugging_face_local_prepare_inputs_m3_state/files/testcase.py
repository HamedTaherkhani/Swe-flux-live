import random
import unittest
from unittest import mock

from haystack.components.generators.chat import HuggingFaceLocalChatGenerator
from haystack.components.generators.chat import hugging_face_local as local_module
from haystack.dataclasses import ChatMessage
from haystack.tools import Tool, Toolset


class DeterministicTokenizer:
    def __init__(self, seed):
        self.pad_token_id = 0 if seed % 3 == 0 else 70 + seed
        self.eos_token_id = 900 + seed

    def apply_chat_template(self, messages, **kwargs):
        checksum = sum(
            sum(ord(char) for char in str(message.get("content", "")))
            for message in messages
        )
        tool_count = len(kwargs.get("tools") or [])
        return f"prompt-{len(messages)}-{checksum % 997}-{tool_count}"

    def encode(self, text, add_special_tokens=False):
        return [ord(char) % 31 for char in text]


class DeterministicPipeline:
    def __init__(self, seed):
        self.tokenizer = DeterministicTokenizer(seed)
        self.device = "cpu"
        self.calls = []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, dict(kwargs)))
        score = (sum(ord(char) for char in prompt) + len(kwargs) * 17) % 991
        return [{"generated_text": f"reply-{score}"}]


class StableCriteria:
    def __init__(self, tokenizer, stop_words, device):
        self.size = len(stop_words)
        self.signature = sum(sum(ord(char) for char in word) for word in stop_words) % 101

    def __repr__(self):
        return f"<criteria:{self.size}:{self.signature}>"


class StableCriteriaList(list):
    pass


class StableStreamer:
    def __init__(self, **kwargs):
        self.token_handler = kwargs["stream_handler"]

    def __repr__(self):
        return "<streamer>"


def consume(value: int = 0) -> int:
    return value + 1


class TestPrepareInputsProgramState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patchers = [
            mock.patch.object(local_module, "StopWordsCriteria", StableCriteria),
            mock.patch.object(local_module, "StoppingCriteriaList", StableCriteriaList),
            mock.patch.object(local_module, "HFTokenStreamingHandler", StableStreamer),
        ]
        for patcher in cls.patchers:
            patcher.start()

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(cls.patchers):
            patcher.stop()

    def make_generator(self, seed, *, stop_words=None, tools=None):
        rng = random.Random(seed * 193)
        base_kwargs = {
            "temperature": round(0.15 + rng.random() * 0.7, 4),
            "top_k": 11 + rng.randrange(37),
            "profile": {"band": rng.randrange(9), "active": seed % 2 == 0},
        }
        generator = HuggingFaceLocalChatGenerator(
            model=f"local-{seed}",
            task="text-generation",
            token=None,
            generation_kwargs=base_kwargs,
            stop_words=stop_words,
            tools=tools,
            tool_parsing_function=lambda text: None,
        )
        generator.pipeline = DeterministicPipeline(seed)
        return generator

    def make_messages(self, seed, count):
        rng = random.Random(seed * 811)
        values = []
        accumulator = seed
        for index in range(count):
            accumulator = (accumulator * 29 + rng.randrange(101) + index * index) % 1009
            values.append(ChatMessage.from_user(f"item-{index}-{accumulator}"))
        return values

    def check_success(self, generator, messages, **kwargs):
        result = generator.run(messages=messages, **kwargs)
        self.assertTrue(result.get("replies"))
        self.assertTrue(result["replies"][0].text.startswith("reply-"))
        self.assertEqual(len(generator.pipeline.calls), 1)

    def test_default_merge_with_many_messages(self):
        generator = self.make_generator(3)
        self.check_success(generator, self.make_messages(3, 17))

    def test_call_overrides_and_empty_stop_lists(self):
        generator = self.make_generator(5)
        rng = random.Random(505)
        kwargs = {
            "temperature": round(rng.random(), 5),
            "max_new_tokens": 40 + rng.randrange(80),
            "stop_words": [],
            "stop_sequences": [],
        }
        self.check_success(generator, self.make_messages(5, 19), generation_kwargs=kwargs)

    def test_stop_words_build_criteria(self):
        generator = self.make_generator(7)
        rng = random.Random(707)
        stops = [f"halt-{index}-{rng.randrange(1000)}" for index in range(6)]
        kwargs = {"stop_words": stops, "frequency_penalty": round(rng.random(), 4)}
        self.check_success(generator, self.make_messages(7, 13), generation_kwargs=kwargs)

    def test_stop_sequences_combine_with_instance_words(self):
        rng = random.Random(1103)
        instance_stops = [f"base-{index}-{rng.randrange(500)}" for index in range(4)]
        generator = self.make_generator(11, stop_words=instance_stops)
        call_stops = [f"call-{index}-{rng.randrange(700)}" for index in range(5)]
        kwargs = {"stop_sequences": call_stops, "repetition_penalty": 1 + rng.random()}
        self.check_success(generator, self.make_messages(11, 21), generation_kwargs=kwargs)

    def test_invalid_mixed_stop_values_are_discarded(self):
        generator = self.make_generator(13)
        rng = random.Random(1301)
        mixed = [f"valid-{rng.randrange(100)}" if index % 3 else index for index in range(15)]
        kwargs = {"stop_words": mixed, "min_length": 5 + rng.randrange(25)}
        self.check_success(generator, self.make_messages(13, 16), generation_kwargs=kwargs)

    def test_streaming_reduces_response_count(self):
        generator = self.make_generator(17)
        rng = random.Random(1709)
        kwargs = {
            "num_return_sequences": 3 + rng.randrange(5),
            "top_p": round(0.4 + rng.random() * 0.5, 5),
        }
        self.check_success(
            generator,
            self.make_messages(17, 18),
            generation_kwargs=kwargs,
            streaming_callback=lambda chunk: None,
        )

    def test_explicit_zero_pad_uses_tokenizer_fallback(self):
        generator = self.make_generator(19)
        rng = random.Random(1907)
        kwargs = {
            "pad_token_id": 0,
            "do_sample": bool(rng.randrange(2)),
            "typical_p": round(rng.random(), 6),
        }
        self.check_success(generator, self.make_messages(19, 14), generation_kwargs=kwargs)

    def test_explicit_nonzero_pad_is_preserved(self):
        generator = self.make_generator(23)
        rng = random.Random(2309)
        kwargs = {
            "pad_token_id": 200 + rng.randrange(300),
            "length_penalty": round(0.5 + rng.random() * 1.5, 5),
            "use_cache": bool(rng.randrange(2)),
        }
        self.check_success(generator, self.make_messages(23, 22), generation_kwargs=kwargs)

    def test_empty_message_collection(self):
        generator = self.make_generator(29)
        rng = random.Random(2903)
        kwargs = {"epsilon_cutoff": round(rng.random() / 10, 7)}
        self.check_success(generator, self.make_messages(29, 0), generation_kwargs=kwargs)

    def test_runtime_tool_list(self):
        generator = self.make_generator(31)
        rng = random.Random(3109)
        tool = Tool(
            name=f"counter_{rng.randrange(1000)}",
            description=f"increment {rng.randrange(1000)}",
            parameters={"type": "object", "properties": {"value": {"type": "integer"}}},
            function=consume,
        )
        kwargs = {"max_time": round(0.2 + rng.random(), 6)}
        self.check_success(
            generator,
            self.make_messages(31, 15),
            generation_kwargs=kwargs,
            tools=[tool],
        )

    def test_runtime_toolset_conversion(self):
        generator = self.make_generator(37)
        rng = random.Random(3701)
        tools = [
            Tool(
                name=f"worker_{index}_{rng.randrange(1000)}",
                description=f"worker {rng.randrange(1000)}",
                parameters={"type": "object", "properties": {"value": {"type": "integer"}}},
                function=consume,
            )
            for index in range(3)
        ]
        kwargs = {"eta_cutoff": round(rng.random() / 20, 8)}
        self.check_success(
            generator,
            self.make_messages(37, 20),
            generation_kwargs=kwargs,
            tools=Toolset(tools),
        )

    def test_unloaded_pipeline_fails_through_public_run(self):
        generator = self.make_generator(41)
        generator.pipeline = None
        kwargs = {"penalty_alpha": round(random.Random(4109).random(), 6)}
        with self.assertRaises(Exception):
            generator.run(messages=self.make_messages(41, 12), generation_kwargs=kwargs)

    def test_tools_and_streaming_conflict_through_public_run(self):
        generator = self.make_generator(43)
        rng = random.Random(4303)
        tool = Tool(
            name=f"conflict_{rng.randrange(1000)}",
            description=f"conflict {rng.randrange(1000)}",
            parameters={"type": "object", "properties": {}},
            function=consume,
        )
        kwargs = {"diversity_penalty": round(rng.random(), 6)}
        with self.assertRaises(Exception):
            generator.run(
                messages=self.make_messages(43, 11),
                generation_kwargs=kwargs,
                tools=[tool],
                streaming_callback=lambda chunk: None,
            )
