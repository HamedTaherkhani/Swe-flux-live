import random
import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

from haystack.components.converters.msg import MSGToDocument
from haystack.dataclasses import ByteStream


@dataclass
class _Recipient:
    name: str
    email_address: str


@dataclass
class _Attachment:
    file_bytes: Optional[bytes]
    file_name: str
    mime_type: str


@dataclass
class _Message:
    message_headers: dict[str, str]
    sender: Optional[str]
    recipients: list[_Recipient]
    subject: str
    body: Optional[str]
    attachments: list[_Attachment]


class TestMSGConvertInvocationCounts(unittest.TestCase):
    def _exercise(
        self,
        *,
        seed: int,
        source_count: int,
        recipient_mod: int,
        encrypted_mod: int,
        case_bias: int,
    ) -> None:
        rng = random.Random(seed)
        tokens = [(rng.randrange(1, 10_000) * (index + 3) + seed) for index in range(source_count)]

        def make_message(stream):
            token = int(stream.read().decode("ascii"))
            encrypted = encrypted_mod > 0 and token % encrypted_mod == 0
            headers = {"Content-Type": "application/encrypted-msg" if encrypted else "text/plain"}
            if token % 3:
                headers["Cc" if (token + case_bias) % 2 else "CC"] = f"team-{token % 17}@example.test"
            if token % 5:
                headers["Bcc" if (token + case_bias) % 3 else "BCC"] = f"audit-{token % 19}@example.test"

            recipient_count = (token // 7 + case_bias) % recipient_mod
            recipients = []
            for offset in range(recipient_count):
                name = "" if (token + offset) % 4 == 0 else f"Person {token % 23}-{offset}"
                address = "" if (token + offset) % 6 == 0 else f"user{token % 29}-{offset}@example.test"
                recipients.append(_Recipient(name=name, email_address=address))

            attachments = [
                _Attachment(
                    file_bytes=None if (token + offset) % 4 == 0 else bytes([(token + offset) % 251]) * (offset + 1),
                    file_name=f"part-{token % 31}-{offset}.bin",
                    mime_type="application/octet-stream",
                )
                for offset in range((token + case_bias) % 6)
            ]
            return _Message(
                message_headers=headers,
                sender=None if token % 7 == 0 else f"sender-{token % 37}@example.test",
                recipients=recipients,
                subject="" if token % 8 == 0 else f"subject-{token % 41}",
                body=None if token % 11 == 0 else f"body checksum {token * token % 997}",
                attachments=attachments,
            )

        sources = [
            ByteStream(data=str(token).encode("ascii"), meta={"file_path": f"/mailbox/{seed}/item-{index}.msg"})
            for index, token in enumerate(tokens)
        ]
        converter = object.__new__(MSGToDocument)
        converter.store_full_path = bool(case_bias % 2)

        with patch("haystack.components.converters.msg.Message.load", side_effect=make_message):
            result = converter.run(sources=sources, meta={"scenario": seed, "parity": case_bias % 2})

        expected_documents = sum(
            not (encrypted_mod > 0 and token % encrypted_mod == 0) for token in tokens
        )
        self.assertEqual(len(result["documents"]), expected_documents)
        self.assertTrue(all(document.content is not None for document in result["documents"]))
        self.assertTrue(all(attachment.data for attachment in result["attachments"]))
        self.assertTrue(all("parent_file_path" in attachment.meta for attachment in result["attachments"]))

    def test_sparse_recipients_mixed_headers(self):
        self._exercise(seed=101, source_count=12, recipient_mod=31, encrypted_mod=5, case_bias=1)

    def test_dense_recipients_lower_headers(self):
        self._exercise(seed=211, source_count=18, recipient_mod=37, encrypted_mod=2, case_bias=2)

    def test_encryption_heavy_short_batch(self):
        self._exercise(seed=307, source_count=15, recipient_mod=41, encrypted_mod=3, case_bias=4)

    def test_attachment_heavy_full_paths(self):
        self._exercise(seed=401, source_count=22, recipient_mod=43, encrypted_mod=7, case_bias=5)

    def test_many_empty_recipient_fields(self):
        self._exercise(seed=509, source_count=17, recipient_mod=47, encrypted_mod=4, case_bias=7)

    def test_long_plain_batch(self):
        self._exercise(seed=601, source_count=24, recipient_mod=53, encrypted_mod=3, case_bias=8)

    def test_alternating_header_case(self):
        self._exercise(seed=709, source_count=11, recipient_mod=59, encrypted_mod=5, case_bias=11)

    def test_subject_and_body_gaps(self):
        self._exercise(seed=809, source_count=26, recipient_mod=61, encrypted_mod=6, case_bias=13)

    def test_dense_batch_with_skips(self):
        self._exercise(seed=907, source_count=28, recipient_mod=67, encrypted_mod=4, case_bias=16)

    def test_minimal_messages(self):
        self._exercise(seed=1009, source_count=9, recipient_mod=71, encrypted_mod=3, case_bias=17)

    def test_wide_recipient_distribution(self):
        self._exercise(seed=1103, source_count=20, recipient_mod=73, encrypted_mod=8, case_bias=19)

    def test_final_mixed_distribution(self):
        self._exercise(seed=1201, source_count=23, recipient_mod=79, encrypted_mod=9, case_bias=23)