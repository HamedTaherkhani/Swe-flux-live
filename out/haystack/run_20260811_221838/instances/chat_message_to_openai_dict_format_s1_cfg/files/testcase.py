import random
import unittest

from haystack.dataclasses import ChatMessage, ToolCall


class TestChatMessageOpenAIPath(unittest.TestCase):
    def test_programmatic_mixed_tool_calls(self):
        seed = sum((index + 1) * ord(char) for index, char in enumerate("control-flow"))
        rng = random.Random(seed)

        first_message = ChatMessage.from_user(
            "".join(chr(ord("a") + rng.randrange(26)) for _ in range(37))
        )
        first_result = first_message.to_openai_dict_format()

        tool_calls = []
        rolling = seed
        for index in range(29):
            sample = rng.randrange(1, 10_000)
            rolling = (rolling * 41 + sample + index * index) % 1_000_003
            call_id = f"call-{rolling:x}" if (sample + rolling + index) % 5 in {1, 4} else None
            tool_calls.append(
                ToolCall(
                    tool_name=f"tool_{chr(ord('a') + rolling % 26)}_{index % 7}",
                    arguments={
                        "index": index,
                        "sample": sample,
                        "parity": (rolling ^ sample) & 1,
                        "window": [(rolling >> shift) & 15 for shift in range(0, 12, 3)],
                    },
                    id=call_id,
                )
            )

        assistant_text = "-".join(str((rolling >> shift) & 31) for shift in range(0, 25, 5))
        second_message = ChatMessage.from_assistant(
            text=assistant_text,
            name=f"agent-{rolling % 97}",
            tool_calls=tool_calls,
        )
        second_result = second_message.to_openai_dict_format(require_tool_call_ids=False)

        origin = tool_calls[next(i for i, call in enumerate(tool_calls) if call.id is not None)]
        third_message = ChatMessage.from_tool(
            tool_result=str(sum(call.arguments["sample"] for call in tool_calls)),
            origin=origin,
            error=bool(rolling & 1),
        )
        third_result = third_message.to_openai_dict_format()

        self.assertEqual(first_result["role"], first_message.role.value)
        self.assertEqual(len(second_result["tool_calls"]), len(tool_calls))
        self.assertTrue(all(item["type"].startswith("fun") for item in second_result["tool_calls"]))
        self.assertEqual(third_result.get("tool_call_id"), origin.id)
