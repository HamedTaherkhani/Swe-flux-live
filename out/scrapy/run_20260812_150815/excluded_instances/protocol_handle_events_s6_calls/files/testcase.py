from __future__ import annotations

import hashlib
import random
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from h2.events import (
    ConnectionTerminated,
    DataReceived,
    ResponseReceived,
    SettingsAcknowledged,
    StreamEnded,
    StreamReset,
    UnknownFrameReceived,
    WindowUpdated,
)
from twisted.internet.defer import Deferred

import scrapy.core.http2.protocol as protocol_module
from scrapy.core.http2.protocol import H2ClientFactory


class GeneratedConnection:
    event_types = (
        ConnectionTerminated,
        DataReceived,
        ResponseReceived,
        StreamEnded,
        StreamReset,
        WindowUpdated,
        SettingsAcknowledged,
        UnknownFrameReceived,
    )

    def __init__(self):
        self.payload_digests = []

    @staticmethod
    def _make_event(event_type, ordinal):
        stream_id = 1001 + ordinal * 2
        if event_type is DataReceived:
            data = hashlib.blake2s(str(ordinal).encode(), digest_size=7).digest()
            return event_type(
                stream_id=stream_id,
                data=data,
                flow_controlled_length=len(data),
            )
        if event_type is ResponseReceived:
            return event_type(
                stream_id=stream_id,
                headers=[(":status", str(200 + ordinal % 5))],
            )
        if event_type is StreamEnded:
            return event_type(stream_id=stream_id)
        if event_type is StreamReset:
            return event_type(stream_id=stream_id, error_code=ordinal % 14)
        if event_type is WindowUpdated:
            return event_type(stream_id=0, delta=ordinal + 1)
        if event_type is UnknownFrameReceived:
            return event_type(frame=SimpleNamespace(kind=ordinal % 6))
        return event_type()

    def receive_data(self, payload):
        digest = hashlib.sha256(payload).digest()
        self.payload_digests.append(digest)
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        labels = list(range(len(self.event_types))) * 4
        rng.shuffle(labels)
        return [
            self._make_event(self.event_types[label], ordinal)
            for ordinal, label in enumerate(labels)
        ]

    def data_to_send(self):
        return self.payload_digests[-1][:5]


class FakeSettings:
    @staticmethod
    def getint(_name):
        return 0


class FakeTransport:
    connected = True

    def __init__(self):
        self.writes = []
        self.losses = 0

    def write(self, data):
        self.writes.append(data)

    def loseConnection(self):
        self.losses += 1

    @staticmethod
    def getPeerCertificate():
        return SimpleNamespace(serial=37)


class FakeCertificate:
    def __init__(self, original):
        self.original = original


class ProtocolEventDispatchTest(unittest.TestCase):
    def test_generated_frames_via_data_received(self):
        source_rng = random.Random(6_021_947)
        payloads = [
            bytes(source_rng.randrange(1, 256) for _ in range(47 + batch * 11))
            for batch in range(3)
        ]

        crawler = SimpleNamespace(settings=FakeSettings())
        factory = H2ClientFactory(
            SimpleNamespace(host=b"example.invalid"),
            crawler,
            Deferred(),
        )
        client = factory.buildProtocol(SimpleNamespace())
        client.conn = GeneratedConnection()
        client.transport = FakeTransport()
        client.resetTimeout = lambda: None

        with mock.patch.object(protocol_module, "Certificate", FakeCertificate):
            for payload in payloads:
                client.dataReceived(payload)

        digest_multiplicities = Counter(client.conn.payload_digests)
        self.assertEqual(sum(digest_multiplicities.values()), len(payloads))
        self.assertTrue(all(count == 1 for count in digest_multiplicities.values()))
        self.assertTrue(client.metadata["settings_acknowledged"])
        self.assertTrue(client.transport.writes)
        self.assertGreater(client.transport.losses, 0)
