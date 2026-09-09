import asyncio
import random
import unittest
from typing import Any, Optional, Union

from haystack import component
from haystack.components.agents import Agent
from haystack.dataclasses import ChatMessage, ToolCall
from haystack.tools import Tool, Toolset


def rotate_value(value: int) -> dict[str, int]:
    return {"value": ((value << 2) ^ (value >> 1)) % 997}


def fold_value(value: int) -> dict[str, int]:
    return {"value": (value * value + 3 * value + 11) % 991}


def halt_value(value: int) -> dict[str, int]:
    return {"value": -value}


@component
class ScheduledChatGenerator:
    def __init__(self, schedule: tuple[tuple[str, int], ...]) -> None:
        self.schedule = schedule
        self.position = 0

    @component.output_types(replies=list[ChatMessage])
    def run(
        self,
        messages: list[ChatMessage],
        tools: Optional[Union[list[Tool], Toolset]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise AssertionError("the asynchronous component path was not used")

    @component.output_types(replies=list[ChatMessage])
    async def run_async(
        self,
        messages: list[ChatMessage],
        tools: Optional[Union[list[Tool], Toolset]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        tool_name, base_value = self.schedule[self.position]
        mixed_value = base_value ^ (len(messages) * (self.position + 3))
        call = ToolCall(
            tool_name=tool_name,
            arguments={"value": mixed_value},
            id=f"step-{self.position:x}-{mixed_value % 97:x}",
        )
        self.position += 1
        return {"replies": [ChatMessage.from_assistant(tool_calls=[call])]}


class AgentRunAsyncCallOrderTest(unittest.TestCase):
    def test_programmatic_tool_cycles(self) -> None:
        rng = random.Random(0x5A17)
        rolling = rng.randrange(100, 500)
        schedule_items = []
        for index in range(17 + rng.randrange(5)):
            rolling = (rolling * 73 + rng.randrange(1, 89) + index * index) % 1009
            tool_name = ("rotate_value", "fold_value")[(rolling ^ index) & 1]
            schedule_items.append((tool_name, rolling))
        schedule = tuple(schedule_items)

        parameters = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        }
        tools = [
            Tool(name=fn.__name__, description=fn.__doc__ or fn.__name__, parameters=parameters, function=fn)
            for fn in (rotate_value, fold_value, halt_value)
        ]
        generator = ScheduledChatGenerator(schedule)
        agent = Agent(
            chat_generator=generator,
            tools=tools,
            exit_conditions=[halt_value.__name__],
            max_agent_steps=len(schedule),
        )

        initial_messages = [
            ChatMessage.from_user(f"seed-fragment-{value:x}")
            for value in (rng.randrange(2**16) for _ in range(7))
        ]
        result = asyncio.run(agent.run_async(messages=initial_messages))

        self.assertEqual(generator.position, len(schedule))
        self.assertGreater(len(result["messages"]), len(initial_messages))
        self.assertIs(result["last_message"], result["messages"][-1])
