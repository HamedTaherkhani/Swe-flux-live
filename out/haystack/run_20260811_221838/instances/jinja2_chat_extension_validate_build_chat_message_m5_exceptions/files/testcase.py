import json
import unittest
from unittest.mock import patch

from jinja2.sandbox import SandboxedEnvironment

from haystack.dataclasses.chat_message import (
    ChatMessage,
    ReasoningContent,
    TextContent,
    ToolCall,
    ToolCallResult,
)
from haystack.dataclasses.image_content import ImageContent
from haystack.utils.jinja2_chat_extension import ChatMessageExtension, templatize_part


class TestGeneratedChatMessageValidation(unittest.TestCase):
    _CASE_COUNT = len("validation-cases!!")

    @staticmethod
    def _reraised(operation):
        try:
            return operation()
        except Exception:
            try:
                raise
            except Exception:
                raise

    @classmethod
    def _dispatch(cls, original):
        def invoke(**kwargs):
            meta = kwargs.get("meta") or {}
            mode = meta.get("mode", 0)
            token = meta.get("token", 1)

            if mode == 1:
                return cls._reraised(lambda: tuple(token))
            if mode == 2:
                return cls._reraised(lambda: meta[f"absent-{token * token}"])
            if mode == 3:
                return cls._reraised(lambda: token // (token - token))
            if mode == 4:
                return cls._reraised(lambda: bytes([128 + token % (cls._CASE_COUNT * 4)]).decode("ascii"))
            if mode == 5:
                return cls._reraised(lambda: next(iter(range(token - token))))
            if mode == 6:
                try:
                    getattr(object(), f"discarded_{token}")
                except Exception:
                    pass
            return original(**kwargs)

        return invoke

    @staticmethod
    def _case_payload(selector, token):
        call = ToolCall(
            tool_name=f"lookup_{token % 7}",
            arguments={"value": token, "parity": token % 2},
            id=f"call_{token * 3 + 1}",
        )
        result = ToolCallResult(
            result=f"result_{token * token}",
            origin=call,
            error=bool(token % 2),
        )
        text_a = TextContent(text=f"alpha_{token * 5}")
        text_b = TextContent(text=f"beta_{token * 7}")
        reasoning = ReasoningContent(
            reasoning_text=f"reason_{token * 11}",
            extra={"step": token % 5},
        )
        image = ImageContent(base64_image="/9j/AA==", mime_type="image/jpeg")

        if selector == 0:
            return "user", 0, "plain", []
        if selector == 1:
            return "user", 0, "parts", [call]
        if selector == 2:
            return "system", 0, "parts", [call]
        if selector == 3:
            return "system", 0, "parts", [text_a, text_b]
        if selector == 4:
            return "assistant", 0, "parts", [text_a, text_b]
        if selector == 5:
            return "assistant", 0, "parts", [reasoning]
        if selector == 6:
            return "assistant", 0, "mixed", [image]
        if selector == 7:
            return "tool", 0, "plain", []
        if selector == 8:
            return "tool", 0, "parts", [result, result]
        if selector == 9:
            return "tool", 0, "mixed", [result]
        if selector == 10:
            return f"visitor_{token % 9}", 0, "plain", []
        if selector == 11:
            return "user", 1, "plain", []
        if selector == 12:
            return "system", 2, "plain", []
        if selector == 13:
            return "assistant", 3, "parts", [call]
        if selector == 14:
            return "tool", 4, "parts", [result]
        if selector == 15:
            return "user", 6, "plain", []
        return "assistant", 5, "parts", [call]

    @staticmethod
    def _template(environment, body_kind):
        if body_kind == "parts":
            body = "{% for item in items %}{{ item | templatize_part }}{% endfor %}"
        elif body_kind == "mixed":
            body = "prefix_{{ token * 13 }}{% for item in items %}{{ item | templatize_part }}{% endfor %}"
        else:
            body = "payload_{{ token * 17 + 3 }}"
        source = (
            '{% message role=role name="generated" meta={"mode": mode, "token": token} %}'
            + body
            + "{% endmessage %}"
        )
        return environment.from_string(source)

    def _exercise(self, seed, rounds):
        environment = SandboxedEnvironment(extensions=[ChatMessageExtension])
        environment.filters["templatize_part"] = templatize_part
        originals = {
            "from_user": ChatMessage.from_user,
            "from_system": ChatMessage.from_system,
            "from_assistant": ChatMessage.from_assistant,
            "from_tool": ChatMessage.from_tool,
        }
        failed = 0
        completed = 0
        digest = 0

        patches = [
            patch.object(ChatMessage, name, new=self._dispatch(original))
            for name, original in originals.items()
        ]
        for active_patch in patches:
            active_patch.start()
        try:
            for index in range(rounds):
                cycle = index // self._CASE_COUNT
                selector = (index + seed * seed + cycle * (seed % 7)) % self._CASE_COUNT
                token = (seed + 3) * (index + 5) + index * index
                role, mode, body_kind, items = self._case_payload(selector, token)
                template = self._template(environment, body_kind)
                try:
                    rendered = template.render(role=role, mode=mode, token=token, items=items)
                except BaseException as caught:
                    failed += 1
                    digest ^= len(str(caught)) * (index + 1)
                else:
                    completed += 1
                    decoded = json.loads(rendered)
                    digest ^= len(decoded["content"]) + len(decoded["meta"])
        finally:
            for active_patch in reversed(patches):
                active_patch.stop()

        self.assertEqual(failed + completed, rounds)
        self.assertGreater(failed, 0)
        self.assertGreater(completed, 0)
        self.assertIsInstance(digest, int)

    def test_seeded_wave_alpha(self):
        self._exercise(5, 33)

    def test_seeded_wave_bravo(self):
        self._exercise(7, 34)

    def test_seeded_wave_charlie(self):
        self._exercise(11, 37)

    def test_seeded_wave_delta(self):
        self._exercise(13, 40)

    def test_seeded_wave_echo(self):
        self._exercise(17, 43)

    def test_seeded_wave_foxtrot(self):
        self._exercise(19, 46)

    def test_seeded_wave_golf(self):
        self._exercise(23, 49)

    def test_seeded_wave_hotel(self):
        self._exercise(29, 52)

    def test_seeded_wave_india(self):
        self._exercise(47, 55)

    def test_seeded_wave_juliet(self):
        self._exercise(37, 58)

    def test_seeded_wave_kilo(self):
        self._exercise(41, 61)

    def test_seeded_wave_lima(self):
        self._exercise(43, 67)
