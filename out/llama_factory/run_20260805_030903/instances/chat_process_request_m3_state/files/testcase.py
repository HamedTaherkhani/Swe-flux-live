import asyncio
import random
import unittest
from types import SimpleNamespace

from llamafactory.api.chat import create_chat_completion_response
from llamafactory.api.protocol import (
    ChatCompletionRequest,
    Function,
    FunctionCall,
    MultimodalInputItem,
    Role,
)


class _ChatModelHarness:
    def __init__(self):
        self.calls = []

    async def achat(self, messages, system, tools, images, videos, audios, **kwargs):
        self.calls.append((messages, system, tools, images, videos, audios, kwargs))
        weighted_size = sum(
            (index + 1) * sum(ord(character) for character in message["content"])
            for index, message in enumerate(messages)
        )
        return [
            SimpleNamespace(
                response_text=f"reply-{weighted_size % 1009}",
                finish_reason="stop",
                prompt_length=len(messages) + weighted_size % 17,
                response_length=1 + weighted_size % 13,
            )
        ]


class TestChatRequestProgramState(unittest.TestCase):
    def test_seeded_mixed_message_batches_through_public_api(self):
        rng = random.Random(sum((index + 3) * ord(char) for index, char in enumerate(self.id())))
        chat_model = _ChatModelHarness()
        responses = []

        for batch_index in range(4):
            messages = [
                {
                    "role": Role.SYSTEM,
                    "content": "".join(
                        chr(ord("a") + (rng.randrange(26) + offset) % 26)
                        for offset in range(9 + batch_index)
                    ),
                }
            ]
            turn_count = 19 + 2 * batch_index
            for turn_index in range(turn_count):
                role = Role.USER if turn_index % 2 == 0 else Role.ASSISTANT
                if turn_index % 10 == 8:
                    role = Role.TOOL
                elif turn_index % 10 == 9:
                    role = Role.FUNCTION

                if role == Role.ASSISTANT and (turn_index + batch_index) % 6 == 1:
                    call_count = 1 + (turn_index + batch_index) % 3
                    tool_calls = []
                    for call_index in range(call_count):
                        name = "".join(
                            chr(ord("a") + (rng.randrange(26) + call_index + shift) % 26)
                            for shift in range(5 + call_index)
                        )
                        argument_value = sum(
                            (position + 1) * rng.randrange(1, 97)
                            for position in range(4 + batch_index)
                        )
                        tool_calls.append(
                            FunctionCall(
                                id=f"generated-{batch_index}-{turn_index}-{call_index}",
                                function=Function(
                                    name=name,
                                    arguments=f'{{"value": {argument_value}, "slot": {call_index}}}',
                                ),
                            )
                        )
                    messages.append({"role": role, "content": None, "tool_calls": tool_calls})
                    continue

                item_count = 3 + (turn_index * turn_index + batch_index) % 5
                items = []
                rolling = rng.randrange(101)
                for item_index in range(item_count):
                    rolling = (rolling * 37 + rng.randrange(997) + turn_index + item_index) % 10007
                    fragment = "".join(
                        chr(ord("a") + (rolling + rng.randrange(26) + position) % 26)
                        for position in range(4 + (item_index + turn_index) % 6)
                    )
                    items.append(MultimodalInputItem(type="text", text=f"{fragment}-{rolling:x}"))
                messages.append({"role": role, "content": items})

            request = ChatCompletionRequest(
                model=f"generated-model-{batch_index}",
                messages=messages,
                temperature=(rng.randrange(31) + 50) / 100,
                max_tokens=20 + rng.randrange(19),
            )
            responses.append(asyncio.run(create_chat_completion_response(request, chat_model)))

        self.assertEqual(len(chat_model.calls), len(responses))
        self.assertTrue(all(len(response.choices) == 1 for response in responses))
        self.assertTrue(all(response.choices[0].message.content.startswith("reply-") for response in responses))
        self.assertTrue(all(len(call[0]) >= 19 for call in chat_model.calls))
