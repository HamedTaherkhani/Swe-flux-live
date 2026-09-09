from __future__ import annotations

import random
import unittest
from typing import Any

from haystack import component
from haystack.components.agents import Agent
from haystack.dataclasses import ChatMessage, ToolCall
from haystack.tools import Tool


def _fold(value: int, salt: int) -> str:
    return f"{(value * value + salt * 17) % 997}:{(value ^ (salt << 2)) % 89}"


@component
class ProgrammedChatGenerator:
    def __init__(self, seed: int, tool_rounds: int, width_bias: int):
        self._rng = random.Random(seed)
        self._tool_rounds = tool_rounds
        self._width_bias = width_bias
        self._calls = 0

    @component.output_types(replies=list[ChatMessage])
    def run(self, messages: list[ChatMessage], tools: Any = None, **kwargs: Any) -> dict[str, Any]:
        call_index = self._calls
        self._calls += 1
        width = 1 + ((self._rng.randrange(29) + self._width_bias + call_index) % 3)
        if call_index >= self._tool_rounds:
            replies = [
                ChatMessage.from_assistant(
                    f"complete-{_fold(len(messages) + offset, self._width_bias + call_index)}"
                )
                for offset in range(width)
            ]
        else:
            replies = []
            for offset in range(width):
                raw = self._rng.randrange(10_000) + len(messages) * (offset + 1)
                replies.append(
                    ChatMessage.from_assistant(
                        tool_calls=[
                            ToolCall(
                                tool_name="fold_tool",
                                arguments={"value": raw, "salt": self._width_bias + call_index + offset},
                            )
                        ]
                    )
                )
        return {"replies": replies}


class TestAgentRunInvariants(unittest.TestCase):
    def _exercise(
        self,
        *,
        seed: int,
        tool_rounds: int,
        max_steps: int,
        width_bias: int,
        user_count: int,
        system_prompt: bool = False,
        exit_on_tool: bool = False,
        omit_tools: bool = False,
    ) -> None:
        generator = ProgrammedChatGenerator(seed, tool_rounds, width_bias)
        tools = [] if omit_tools else [
            Tool(
                name="fold_tool",
                description="Combines two generated integers.",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}, "salt": {"type": "integer"}},
                    "required": ["value", "salt"],
                },
                function=_fold,
            )
        ]
        exit_conditions = ["fold_tool"] if exit_on_tool else ["text"]
        agent = Agent(
            chat_generator=generator,
            tools=tools,
            system_prompt="Keep processing generated requests." if system_prompt else None,
            exit_conditions=exit_conditions,
            max_agent_steps=max_steps,
            tool_invoker_kwargs={"max_workers": 1} if tools else None,
        )
        messages = [
            ChatMessage.from_user(
                f"request-{index}-{_fold((seed % 97) + index, width_bias)}"
            )
            for index in range(user_count)
        ]

        result = agent.run(messages)

        self.assertIsInstance(result, dict)
        self.assertIn("messages", result)
        self.assertGreater(len(result["messages"]), user_count)
        self.assertIs(result["last_message"], result["messages"][-1])

    def test_seeded_short_completion(self):
        self._exercise(seed=101, tool_rounds=4, max_steps=9, width_bias=2, user_count=2)

    def test_seeded_medium_completion(self):
        self._exercise(seed=211, tool_rounds=6, max_steps=12, width_bias=5, user_count=3)

    def test_seeded_long_completion(self):
        self._exercise(seed=307, tool_rounds=9, max_steps=15, width_bias=8, user_count=4)

    def test_maximum_step_cutoff_even(self):
        self._exercise(seed=401, tool_rounds=17, max_steps=8, width_bias=1, user_count=1)

    def test_maximum_step_cutoff_odd(self):
        self._exercise(seed=503, tool_rounds=19, max_steps=11, width_bias=4, user_count=5)

    def test_system_prompt_completion(self):
        self._exercise(
            seed=601, tool_rounds=5, max_steps=10, width_bias=7, user_count=2, system_prompt=True
        )

    def test_system_prompt_cutoff(self):
        self._exercise(
            seed=709, tool_rounds=23, max_steps=7, width_bias=10, user_count=3, system_prompt=True
        )

    def test_immediate_text_batch(self):
        self._exercise(seed=809, tool_rounds=0, max_steps=6, width_bias=3, user_count=6)

    def test_single_tool_exit_condition(self):
        self._exercise(
            seed=907, tool_rounds=12, max_steps=14, width_bias=6, user_count=2, exit_on_tool=True
        )

    def test_generator_mode_without_tools(self):
        self._exercise(
            seed=1009, tool_rounds=16, max_steps=13, width_bias=9, user_count=4, omit_tools=True
        )

    def test_high_width_bias_completion(self):
        self._exercise(seed=1103, tool_rounds=7, max_steps=13, width_bias=14, user_count=3)

    def test_deeper_seeded_completion(self):
        self._exercise(seed=1201, tool_rounds=13, max_steps=18, width_bias=11, user_count=2)
