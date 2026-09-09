import random
import unittest

from haystack import Document
from haystack.components.builders.answer_builder import AnswerBuilder
from haystack.dataclasses.chat_message import ChatMessage


class TestAnswerBuilderRunInvariants(unittest.TestCase):
    def _exercise(
        self,
        seed,
        count,
        *,
        chat=False,
        document_count=0,
        references_per_reply=None,
        metadata_width=0,
        message_metadata_width=0,
        pattern=False,
        last_message_only=False,
        miss_index=None,
        runtime_pattern=False,
        runtime_reference_pattern=False,
    ):
        rng = random.Random(seed * 1009 + count * 97)
        documents = [
            Document(
                content=f"doc-{index}-{rng.randrange(100_000)}",
                meta={"bucket": (seed + index * 7) % 11},
            )
            for index in range(document_count)
        ]
        replies = []
        metadata = []
        for index in range(count):
            token = (rng.randrange(1_000_003) + seed * (index + 3) + index * index) % 1_000_003
            body = f"payload=value_{index}_{token}"
            if miss_index == index:
                body = f"alternate-value-{token}"
            if references_per_reply is not None and document_count:
                refs = [
                    1 + ((rng.randrange(document_count) + index + offset * offset) % document_count)
                    for offset in range(references_per_reply)
                ]
                body += "".join(f"[{ref}]" for ref in refs)

            if chat:
                message_meta = {
                    f"message_{slot}_{(seed + index + slot) % 13}": (token + slot * 17) % 101
                    for slot in range(message_metadata_width)
                }
                reply = ChatMessage.from_assistant(body, meta=message_meta)
            else:
                reply = body
            replies.append(reply)
            metadata.append(
                {
                    f"given_{slot}_{(index + slot + seed) % 17}": (token * (slot + 3)) % 109
                    for slot in range(metadata_width)
                }
            )

        capture_pattern = r"payload=(value_\d+_\d+)"
        reference_pattern = r"\[(\d+)\]"
        builder = AnswerBuilder(
            pattern=None if runtime_pattern or not pattern else capture_pattern,
            reference_pattern=None
            if runtime_reference_pattern or references_per_reply is None
            else reference_pattern,
            last_message_only=last_message_only,
        )
        kwargs = {}
        if runtime_pattern and pattern:
            kwargs["pattern"] = capture_pattern
        if runtime_reference_pattern and references_per_reply is not None:
            kwargs["reference_pattern"] = reference_pattern

        result = builder.run(
            query=f"query-{seed}-{sum(ord(char) for char in str(seed))}",
            replies=replies,
            meta=metadata if metadata_width else None,
            documents=documents or None,
            **kwargs,
        )
        answers = result.get("answers")
        expected_count = int(bool(replies)) if last_message_only else len(replies)
        self.assertEqual(len(answers), expected_count)
        self.assertTrue(all(answer.query.startswith("query-") for answer in answers))
        self.assertTrue(all("all_messages" in answer.meta for answer in answers))
        if pattern and miss_index is None:
            self.assertTrue(all(answer.data.startswith("value_") for answer in answers))
        return answers

    def test_chat_references_and_wide_metadata(self):
        self._exercise(
            7,
            19,
            chat=True,
            document_count=8,
            references_per_reply=4,
            metadata_width=3,
            message_metadata_width=2,
            pattern=True,
        )

    def test_strings_without_documents_or_pattern(self):
        self._exercise(11, 23, metadata_width=1)

    def test_documents_without_reference_filter(self):
        self._exercise(13, 17, document_count=5, metadata_width=2, pattern=True)

    def test_runtime_patterns_with_sparse_metadata(self):
        self._exercise(
            17,
            21,
            document_count=9,
            references_per_reply=1,
            metadata_width=0,
            pattern=True,
            runtime_pattern=True,
            runtime_reference_pattern=True,
        )

    def test_chat_messages_without_given_metadata(self):
        self._exercise(19, 18, chat=True, message_metadata_width=4, pattern=True)

    def test_last_message_only_with_many_inputs(self):
        self._exercise(
            23,
            27,
            chat=True,
            document_count=6,
            references_per_reply=5,
            metadata_width=2,
            message_metadata_width=1,
            pattern=True,
            last_message_only=True,
        )

    def test_duplicate_references_from_strings(self):
        self._exercise(
            29,
            16,
            document_count=3,
            references_per_reply=7,
            metadata_width=4,
            pattern=True,
        )

    def test_single_nonmatching_pattern_reply(self):
        self._exercise(
            31,
            20,
            chat=True,
            document_count=7,
            references_per_reply=2,
            metadata_width=1,
            message_metadata_width=2,
            pattern=True,
            miss_index=13,
        )

    def test_empty_reply_collection(self):
        self._exercise(
            37,
            0,
            chat=True,
            document_count=4,
            references_per_reply=3,
            metadata_width=3,
            pattern=True,
        )

    def test_one_reference_and_wide_given_metadata(self):
        self._exercise(
            41,
            24,
            document_count=11,
            references_per_reply=1,
            metadata_width=5,
            pattern=False,
        )

    def test_runtime_reference_override_for_chat(self):
        self._exercise(
            43,
            15,
            chat=True,
            document_count=10,
            references_per_reply=3,
            metadata_width=2,
            message_metadata_width=3,
            pattern=False,
            runtime_reference_pattern=True,
        )

    def test_two_references_with_empty_given_dicts(self):
        self._exercise(
            47,
            22,
            document_count=12,
            references_per_reply=2,
            metadata_width=0,
            pattern=True,
        )
