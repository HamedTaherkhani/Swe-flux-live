from __future__ import annotations

import hashlib
import random
import unittest
from types import SimpleNamespace
from unittest import mock

from scrapy.core.http2.stream import Stream, StreamCloseReason
from scrapy.http import Headers, Request


class RecordingProtocol:
    def __init__(self, token: bytes):
        self.metadata = {
            "ip_address": f"192.0.2.{token[0] % 200 + 1}",
            "uri": SimpleNamespace(
                host=hashlib.blake2s(token, digest_size=8).hexdigest().encode(),
                port=8000 + int.from_bytes(token[1:3], "big") % 1000,
            ),
        }
        self.popped = []

    def pop_stream(self, stream_id):
        self.popped.append(stream_id)


class RecordingDeferred:
    def __init__(self):
        self.failures = []

    def errback(self, failure):
        self.failures.append(failure)


class StreamCloseDataFlowTest(unittest.TestCase):
    def test_generated_close_scenarios(self):
        rng = random.Random(7_903_211)
        reasons = list(StreamCloseReason)
        schedule = reasons * (3 + len(reasons) // 3)
        rng.shuffle(schedule)
        closed_streams = []
        protocols = []
        deferreds = []

        with mock.patch.object(Stream, "_fire_response_deferred", autospec=True) as fire:
            for ordinal, reason in enumerate(schedule):
                token = hashlib.sha256(
                    f"{rng.getrandbits(96)}:{ordinal}".encode()
                ).digest()
                protocol = RecordingProtocol(token)
                deferred = RecordingDeferred()
                request = Request(
                    f"https://example.invalid/{hashlib.sha1(token).hexdigest()}"
                )
                stream = Stream.__new__(Stream)
                stream.stream_id = int.from_bytes(token[:4], "big") | 1
                stream._request = request
                stream._protocol = protocol
                stream._download_maxsize = 1 + int.from_bytes(token[4:7], "big")
                stream._deferred_response = deferred
                stream.metadata = {"stream_closed_server": False}
                status_seed = token[7] ^ token[13]
                stream._response = {
                    "headers": Headers(),
                    "flow_controlled_size": int.from_bytes(token[8:12], "big"),
                    "status": None if status_seed % 3 else 200 + status_seed % 37,
                }
                if token[12] & 1:
                    stream._response["headers"][b"Content-Length"] = str(
                        int.from_bytes(token[14:18], "big")
                    )
                error_count = token[18] % 4
                errors = tuple(
                    RuntimeError(hashlib.blake2b(token + bytes([index])).hexdigest())
                    for index in range(error_count)
                )

                stream.close(
                    reason,
                    errors if token[19] & 1 else None,
                    from_protocol=bool(token[20] & 1),
                )
                closed_streams.append(stream)
                protocols.append(protocol)
                deferreds.append(deferred)

        self.assertEqual(len(closed_streams), len(schedule))
        self.assertTrue(all(stream.metadata["stream_closed_server"] for stream in closed_streams))
        self.assertTrue(any(protocol.popped for protocol in protocols))
        self.assertTrue(any(not protocol.popped for protocol in protocols))
        self.assertTrue(any(deferred.failures for deferred in deferreds))
        self.assertGreater(fire.call_count, len(reasons))
