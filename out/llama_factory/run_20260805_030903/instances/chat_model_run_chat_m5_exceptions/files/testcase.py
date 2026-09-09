import random
import sys
import unittest
from unittest.mock import patch

from llamafactory import cli as cli_module
from llamafactory.chat import chat_model as chat_module


class _ScriptedInput:
    def __init__(self, entries):
        self.entries = entries
        self.position = 0

    def __call__(self, _prompt):
        kind, value = self.entries[self.position]
        self.position += 1
        if kind:
            return value.decode("utf-8")
        return value


class _TextModel:
    def stream_chat(self, messages):
        content = messages[-1]["content"]
        width = 2 + (sum(map(ord, content)) % 4)
        for offset in range(width):
            yield content[(offset * 3) % len(content) :][:2]


class _NumericModel:
    def stream_chat(self, messages):
        yield len(messages) * len(messages[-1])


class _LookupModel:
    def stream_chat(self, messages):
        key = "".join(chr(value) for value in (117, 110, 107, 110, 111, 119, 110))
        yield messages[-1][key]


class TestChatCliLayeredExceptions(unittest.TestCase):
    def test_seeded_cli_invocations(self):
        seed = sum((index + 7) * ord(char) for index, char in enumerate(self.id()))
        rng = random.Random(seed)

        entries = []
        for ordinal in range(32):
            if (ordinal * ordinal + rng.randrange(11)) % 5 == 0:
                entries.append((1, bytes((0xC0 + ordinal % 16,))))
            else:
                token = "".join(chr(97 + rng.randrange(26)) for _ in range(9 + ordinal % 7))
                entries.append((0, f"{ordinal:02d}-{token}"))
            if ordinal in {9, 23}:
                entries.append((0, "".join(map(chr, (99, 108, 101, 97, 114)))))
        entries.append((0, "".join(map(chr, (101, 120, 105, 116)))))

        scenarios = [
            (_ScriptedInput(entries), _TextModel),
            (_ScriptedInput([]), _TextModel),
            (lambda _prompt: seed % 97, _TextModel),
            (_ScriptedInput([(0, "payload")]), _NumericModel),
            (_ScriptedInput([(0, "payload")]), _LookupModel),
            (_ScriptedInput([(0, "payload")]), lambda: (10**1000).to_bytes(1, "big")),
        ]

        completed = 0
        failed = []
        for input_provider, model_factory in scenarios:
            try:
                with (
                    patch.object(sys, "argv", ["program", "chat"]),
                    patch.object(chat_module, "ChatModel", model_factory),
                    patch("builtins.input", input_provider),
                    patch("builtins.print"),
                ):
                    cli_module.main()
                completed += 1
            except Exception as exc:
                failed.append(exc)

        self.assertEqual(completed + len(failed), len(scenarios))
        self.assertGreater(completed, 0)
        self.assertGreater(len(failed), completed)
        self.assertTrue(all(isinstance(exc, Exception) for exc in failed))
