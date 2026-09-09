import random
import unittest

from haystack.dataclasses import ChatMessage, ImageContent, ToolCall
from haystack.utils.hf import convert_message_to_hf_format


class TestHFMessageDataFlow(unittest.TestCase):
    def test_seeded_mixed_messages(self):
        rng = random.Random(sum(ord(char) for char in "hugging-face-dataflow"))

        content_parts = []
        for index in range(len("multimodal-content-wave--")):
            token = rng.randrange(1, 10_000) ^ (index * index + index)
            if (token + index) % 3:
                content_parts.append(f"segment-{index}-{token:x}")
            else:
                payload = bytes((token >> shift) & 0xFF for shift in (0, 3, 6, 9))
                import base64

                content_parts.append(
                    ImageContent(
                        base64_image=base64.b64encode(payload).decode("ascii"),
                        mime_type="image/png" if index % 2 else None,
                        validation=False,
                    )
                )

        multimodal = ChatMessage.from_user(content_parts=content_parts)
        multimodal_result = convert_message_to_hf_format(multimodal)

        tool_calls = []
        for index in range(len("tool-call-branch-sequence---")):
            token = rng.randrange(10_000, 99_999) + index * (index + 3)
            tool_calls.append(
                ToolCall(
                    tool_name=f"operation_{token % 17}",
                    arguments={"token": token, "bucket": (token ^ index) % 11},
                    id=f"call_{token:x}" if (token + index) % 4 else None,
                )
            )

        assistant = ChatMessage.from_assistant(tool_calls=tool_calls)
        tool_result = convert_message_to_hf_format(assistant)
        text_result = convert_message_to_hf_format(
            ChatMessage.from_system("".join(chr(97 + rng.randrange(26)) for _ in range(19)))
        )
        origins = (
            next(call for call in tool_calls if call.id is not None),
            next(call for call in reversed(tool_calls) if call.id is None),
        )
        returned_tool_results = [
            convert_message_to_hf_format(
                ChatMessage.from_tool(
                    tool_result={
                        "digest": (sum(call.arguments["token"] for call in tool_calls) + offset) % 997
                    },
                    origin=origin,
                )
            )
            for offset, origin in enumerate(origins)
        ]

        self.assertEqual(len(multimodal_result["content"]), len(content_parts))
        self.assertEqual(len(tool_result["tool_calls"]), len(tool_calls))
        self.assertIsInstance(text_result["content"], str)
        self.assertTrue(all("content" in result for result in returned_tool_results))
