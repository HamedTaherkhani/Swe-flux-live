import asyncio
import random
import unittest

from haystack.components.agents import State
from haystack.components.tools import ToolInvoker
from haystack.dataclasses import ChatMessage, ToolCall
from haystack.tools import Tool


def fold_value(value: int, bias: int) -> dict:
    return {"payload": (value * value + bias) % 997, "kind": "fold"}


def twist_value(value: int, bias: int, streaming_callback=None) -> dict:
    return {"payload": ((value ^ bias) * 13) % 991, "kind": "twist"}


def pulse_value(value: int) -> list[int]:
    return [value % 17, (value * 7) % 19]


class TestToolInvokerAsyncCalls(unittest.TestCase):
    def test_seeded_parallel_tool_batch(self):
        rng = random.Random(82471)
        names = ["".join(chr(ord("a") + offset) for offset in code) for code in ((5, 14, 11, 3), (19, 22, 8, 18, 19), (15, 20, 11, 18, 4))]
        functions = [fold_value, twist_value, pulse_value]
        parameters = [
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}, "bias": {"type": "integer"}},
                "required": ["value", "bias"],
            },
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}, "bias": {"type": "integer"}},
                "required": ["value", "bias"],
            },
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        ]
        tools = [
            Tool(
                name=name,
                description=f"Transform generated integer using strategy {index}",
                parameters=parameters[index],
                function=functions[index],
                outputs_to_state={"latest": {"source": "payload"}} if index < 2 else None,
            )
            for index, name in enumerate(names)
        ]

        state = State(schema={"bias": {"type": int}, "latest": {"type": int}})
        state.set("bias", sum(rng.randrange(3, 41) for _ in range(9)))
        calls = []
        for index in range(37):
            selector = (rng.randrange(29) + index * index + state.get("bias")) % 11
            tool_name = names[selector % len(names)] if selector not in {0, 7} else f"absent_{selector}"
            arguments = {"value": rng.randrange(100, 900) ^ (index * 17)}
            if tool_name != names[2] and (index + selector) % 4 == 0:
                arguments["bias"] = rng.randrange(5, 73)
            calls.append(ToolCall(tool_name=tool_name, arguments=arguments, id=f"generated-{index:x}"))

        messages = [
            ChatMessage.from_user("ignore non-tool message"),
            *[
                ChatMessage.from_assistant(tool_calls=calls[start : start + width])
                for start, width in ((0, 13), (13, 11), (24, 13))
            ],
        ]
        streamed = []

        async def collect_chunk(chunk):
            streamed.append(chunk)

        invoker = ToolInvoker(
            tools=[tools[-1]],
            raise_on_failure=False,
            enable_streaming_callback_passthrough=True,
            max_workers=5,
        )
        result = asyncio.run(
            invoker.run_async(
                messages=messages,
                state=state,
                streaming_callback=collect_chunk,
                tools=tools,
            )
        )

        self.assertEqual(len(result["tool_messages"]), len(calls))
        self.assertIs(result["state"], state)
        self.assertGreater(len(streamed), len(messages))
        self.assertTrue(any(message.tool_call_result.error for message in result["tool_messages"]))
