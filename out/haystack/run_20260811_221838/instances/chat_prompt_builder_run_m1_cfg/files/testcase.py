import random
import unittest

from haystack.components.builders.chat_prompt_builder import ChatPromptBuilder
from haystack.dataclasses.chat_message import ChatMessage
from haystack.dataclasses.image_content import ImageContent


def _mixed_messages(seed_text, size_text):
    seed = sum((index + 1) * ord(char) for index, char in enumerate(seed_text))
    generator = random.Random(seed)
    messages = []
    for index in range(len(size_text)):
        selector = generator.randrange(len("roles"))
        text = f"{seed_text}-{index}: {{{{ token }}}}"
        if selector < len("us"):
            messages.append(ChatMessage.from_user(text))
        elif selector == len("us"):
            messages.append(ChatMessage.from_system(text))
        else:
            messages.append(ChatMessage.from_assistant(text))
    return messages


def _active_messages(role_cycle, size_text):
    factories = {
        "u": ChatMessage.from_user,
        "s": ChatMessage.from_system,
    }
    return [
        factories[role_cycle[index % len(role_cycle)]](f"entry-{index}: {{{{ token }}}}")
        for index in range(len(size_text))
    ]


class TestChatPromptBuilderRunCFG(unittest.TestCase):
    def test_default_mixed_template(self):
        template = _mixed_messages("amber", "deterministic-message-set")
        builder = ChatPromptBuilder(template=template, variables=["token"])
        result = builder.run(token="first")
        self.assertEqual(len(result["prompt"]), len(template))
        self.assertTrue(any(message.text.endswith("first") for message in result["prompt"] if message.text))

    def test_runtime_mixed_override(self):
        template = _mixed_messages("beryl", "runtime-template-with-varied-roles")
        builder = ChatPromptBuilder(variables=["token"])
        result = builder.run(template=template, token="second")
        self.assertEqual(len(result["prompt"]), len(template))
        self.assertIsNot(result["prompt"], template)

    def test_all_user_messages(self):
        template = _active_messages("u", "user-only-template")
        builder = ChatPromptBuilder(template=template, variables=["token"])
        result = builder.run(template_variables={"token": "third"})
        self.assertTrue(all(message.is_from("user") for message in result["prompt"]))

    def test_all_system_messages(self):
        template = _active_messages("s", "system-only-template!")
        builder = ChatPromptBuilder(template=template, variables=["token"])
        result = builder.run(token="fourth")
        self.assertTrue(all(message.is_from("system") for message in result["prompt"]))

    def test_all_assistant_messages(self):
        template = [
            ChatMessage.from_assistant(f"assistant-{index}")
            for index in range(len("assistant-pass-through"))
        ]
        builder = ChatPromptBuilder(template=template)
        result = builder.run()
        self.assertTrue(all(left is right for left, right in zip(result["prompt"], template)))

    def test_alternating_user_and_assistant(self):
        template = [
            ChatMessage.from_user(f"user-{index}: {{{{ token }}}}")
            if index % len("ab") == 0
            else ChatMessage.from_assistant(f"assistant-{index}")
            for index in range(len("alternating-role-sequence!"))
        ]
        builder = ChatPromptBuilder(template=template, variables=["token"])
        result = builder.run(token="ignored", template_variables={"token": "winner"})
        self.assertEqual(len(result["prompt"]), len(template))
        self.assertTrue(result["prompt"][0].text.endswith("winner"))

    def test_combined_variable_sources(self):
        template = _active_messages("usu", "combined-variable-source-sequence")
        builder = ChatPromptBuilder(
            template=template,
            variables=["token", "suffix"],
            required_variables=["token"],
        )
        result = builder.run(
            token="keyword",
            suffix="tail",
            template_variables={"token": "replacement"},
        )
        self.assertEqual(len(result["prompt"]), len(template))
        self.assertNotIn("keyword", result["prompt"][-1].text)

    def test_string_template_with_generated_messages(self):
        template = (
            "{% for item in items %}"
            "{% message role='user' %}{{ item }}{% endmessage %}"
            "{% endfor %}"
        )
        items = [f"item-{index * index}" for index in range(len("string-template-items"))]
        builder = ChatPromptBuilder(template=template, variables=["items"])
        result = builder.run(items=items)
        self.assertEqual(len(result["prompt"]), len(items))
        self.assertTrue(all(message.is_from("user") for message in result["prompt"]))

    def test_truthy_tuple_template_is_ignored(self):
        template = tuple(
            ChatMessage.from_user(f"tuple-{index}")
            for index in range(len("tuple-input"))
        )
        builder = ChatPromptBuilder(variables=[])
        result = builder.run(template=template)
        self.assertEqual(result["prompt"], [])

    def test_missing_template_raises(self):
        builder = ChatPromptBuilder()
        with self.assertRaises(ValueError):
            builder.run()

    def test_mixed_object_list_raises(self):
        template = [
            ChatMessage.from_assistant(f"valid-{index}")
            for index in range(len("validated-prefix"))
        ]
        template.append({"not": "a message"})
        builder = ChatPromptBuilder(variables=[])
        with self.assertRaises(ValueError):
            builder.run(template=template)

    def test_forbidden_filter_after_long_prefix(self):
        template = [
            ChatMessage.from_assistant(f"prefix-{index}")
            for index in range(len("filter-error-prefix!"))
        ]
        template.append(ChatMessage.from_user("{{ token | templatize_part }}"))
        builder = ChatPromptBuilder(variables=["token"])
        with self.assertRaises(ValueError):
            builder.run(template=template, token="payload")

    def test_image_only_user_after_mixed_prefix(self):
        template = _mixed_messages("cobalt", "image-error-prefix!!")
        image = ImageContent(base64_image="unused", validation=False)
        template.append(ChatMessage.from_user(content_parts=[image]))
        builder = ChatPromptBuilder(variables=[])
        with self.assertRaises(ValueError):
            builder.run(template=template)

    def test_missing_required_variable_after_assistants(self):
        template = [
            ChatMessage.from_assistant(f"prefix-{index}")
            for index in range(len("required-variable-prefix"))
        ]
        template.append(ChatMessage.from_system("{{ needed }}"))
        builder = ChatPromptBuilder(
            template=template,
            variables=["needed"],
            required_variables=["needed"],
        )
        with self.assertRaises(ValueError):
            builder.run()

    def test_invalid_jinja_after_pass_through_prefix(self):
        template = [
            ChatMessage.from_assistant(f"prefix-{index}")
            for index in range(len("invalid-jinja-prefix"))
        ]
        template.append(ChatMessage.from_user("{{ broken }"))
        builder = ChatPromptBuilder(variables=["broken"])
        with self.assertRaises(Exception) as raised:
            builder.run(template=template, broken="value")
        self.assertNotIsInstance(raised.exception, ValueError)
