from __future__ import annotations

import random
import unittest
import warnings
from io import BytesIO
from unittest.mock import Mock, patch

from twisted.internet.defer import Deferred

warnings.filterwarnings(
    "ignore",
    message="The scrapy.mail module is deprecated",
)

from scrapy.mail import MailSender  # noqa: E402


class MailSenderControlFlowTest(unittest.TestCase):
    def exercise_scenario(
        self,
        *,
        seed: int,
        span: int,
        divisor: int,
        use_attachments: bool,
        use_cc: bool,
        use_charset: bool,
        use_callback: bool,
        debug: bool,
        mimetype: str,
    ) -> None:
        rng = random.Random(seed)
        recipient_count = 1 + rng.randrange(5)
        recipients = [
            f"user-{(seed * (index + 3) + rng.randrange(10_000)) % 65_521:x}"
            f"@example.invalid"
            for index in range(recipient_count)
        ]
        to = recipients[0] if recipient_count == 1 else recipients

        cc_values = [
            f"copy-{(rng.randrange(100_000) ^ seed ^ index):x}@example.invalid"
            for index in range(1 + rng.randrange(4))
        ]
        cc = (cc_values[0] if len(cc_values) == 1 else cc_values) if use_cc else None

        attachments = []
        if use_attachments:
            attachment_types = (
                "application/octet-stream",
                "text/plain",
                "image/png",
                "application/json",
            )
            for index in range(span):
                token = rng.getrandbits(20) ^ (seed * (index + 1))
                if (token + index * index) % divisor:
                    payload_size = 9 + token % 73
                    payload = bytes(
                        (token + offset * (index + 5)) % 256
                        for offset in range(payload_size)
                    )
                    attachments.append(
                        (
                            f"part-{index:x}-{token & 0xFFF:x}.bin",
                            attachment_types[(token + index) % len(attachment_types)],
                            BytesIO(payload),
                        )
                    )

        alphabet = "abcdefhijkmnpqrstuvwxyz"
        body_core = "".join(
            alphabet[rng.randrange(len(alphabet))]
            for _ in range(31 + rng.randrange(37))
        )
        body = f"{body_core}-é" if use_charset else body_core
        subject = "".join(
            chr(65 + ((seed >> (index % 11)) + index * 7) % 26)
            for index in range(13)
        )

        sender = MailSender(
            mailfrom=f"sender-{seed:x}@example.invalid",
            debug=debug,
        )
        deferred = Deferred()
        sender._sendmail = Mock(return_value=deferred)
        captured = []

        def capture(**kwargs):
            captured.append(kwargs)

        callback = capture if use_callback else None
        with patch("twisted.internet.reactor.addSystemEventTrigger") as trigger:
            result = sender.send(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                attachs=attachments,
                mimetype=mimetype,
                charset="utf-8" if use_charset else None,
                _callback=callback,
            )

        if debug:
            self.assertIsNone(result)
            sender._sendmail.assert_not_called()
            trigger.assert_not_called()
        else:
            self.assertIs(result, deferred)
            sender._sendmail.assert_called_once()
            trigger.assert_called_once()

        self.assertEqual(bool(captured), use_callback)
        if captured:
            message = captured[0]["msg"]
            self.assertEqual(message["From"], sender.mailfrom)
            self.assertEqual(bool(message.is_multipart()), bool(attachments))
            self.assertEqual(captured[0]["body"], body)
        if attachments:
            self.assertTrue(all(stream.tell() > 0 for _, _, stream in attachments))

    def test_debug_dense_attachments_with_cc(self):
        self.exercise_scenario(
            seed=731_489,
            span=43,
            divisor=5,
            use_attachments=True,
            use_cc=True,
            use_charset=False,
            use_callback=True,
            debug=True,
            mimetype="text/plain",
        )

    def test_delivery_sparse_attachments_utf8(self):
        self.exercise_scenario(
            seed=284_117,
            span=37,
            divisor=3,
            use_attachments=True,
            use_cc=False,
            use_charset=True,
            use_callback=False,
            debug=False,
            mimetype="text/html",
        )

    def test_debug_plain_without_optional_paths(self):
        self.exercise_scenario(
            seed=906_271,
            span=29,
            divisor=7,
            use_attachments=False,
            use_cc=False,
            use_charset=False,
            use_callback=False,
            debug=True,
            mimetype="text/plain",
        )

    def test_delivery_plain_with_cc_callback(self):
        self.exercise_scenario(
            seed=415_903,
            span=31,
            divisor=4,
            use_attachments=False,
            use_cc=True,
            use_charset=False,
            use_callback=True,
            debug=False,
            mimetype="text/html",
        )

    def test_debug_prime_attachment_walk_utf8(self):
        self.exercise_scenario(
            seed=663_527,
            span=47,
            divisor=6,
            use_attachments=True,
            use_cc=True,
            use_charset=True,
            use_callback=False,
            debug=True,
            mimetype="application/json",
        )

    def test_delivery_attachment_callback_ascii(self):
        self.exercise_scenario(
            seed=128_963,
            span=41,
            divisor=8,
            use_attachments=True,
            use_cc=False,
            use_charset=False,
            use_callback=True,
            debug=False,
            mimetype="text/plain",
        )

    def test_debug_nonmultipart_utf8_callback(self):
        self.exercise_scenario(
            seed=579_341,
            span=23,
            divisor=5,
            use_attachments=False,
            use_cc=True,
            use_charset=True,
            use_callback=True,
            debug=True,
            mimetype="text/plain",
        )

    def test_delivery_wide_attachment_mix(self):
        self.exercise_scenario(
            seed=847_201,
            span=53,
            divisor=9,
            use_attachments=True,
            use_cc=True,
            use_charset=False,
            use_callback=False,
            debug=False,
            mimetype="text/html",
        )

    def test_debug_clustered_attachment_callback(self):
        self.exercise_scenario(
            seed=392_477,
            span=35,
            divisor=4,
            use_attachments=True,
            use_cc=False,
            use_charset=False,
            use_callback=True,
            debug=True,
            mimetype="application/json",
        )

    def test_delivery_nonmultipart_utf8_no_cc(self):
        self.exercise_scenario(
            seed=214_669,
            span=27,
            divisor=6,
            use_attachments=False,
            use_cc=False,
            use_charset=True,
            use_callback=False,
            debug=False,
            mimetype="text/html",
        )

    def test_debug_long_attachment_stride(self):
        self.exercise_scenario(
            seed=958_103,
            span=59,
            divisor=7,
            use_attachments=True,
            use_cc=True,
            use_charset=True,
            use_callback=True,
            debug=True,
            mimetype="text/plain",
        )

    def test_delivery_compact_attachment_stride(self):
        self.exercise_scenario(
            seed=506_353,
            span=33,
            divisor=10,
            use_attachments=True,
            use_cc=False,
            use_charset=True,
            use_callback=True,
            debug=False,
            mimetype="application/json",
        )
