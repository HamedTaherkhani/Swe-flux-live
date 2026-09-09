import asyncio
import random
import unittest

from fastapi import WebSocketDisconnect

from docs_src.websockets_.tutorial003_py310 import manager, websocket_endpoint


class GeneratedWebSocket:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.accepted = False
        self.receive_calls = 0
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        self.receive_calls += 1
        try:
            return next(self._messages)
        except StopIteration:
            raise WebSocketDisconnect() from None

    async def send_text(self, message):
        self.sent.append(message)


class TestWebSocketEndpointRuntime(unittest.TestCase):
    def test_dynamic_function_coverage(self):
        rng = random.Random(2024)
        message_count = 48 + sum(rng.randrange(13) for _ in range(22))
        messages = [
            f"{index:08x}:{rng.randrange(99_999):05d}:{(index * 31 + rng.randrange(197)) % 257}"
            for index in range(message_count)
        ]
        websocket = GeneratedWebSocket(messages)

        manager.active_connections.clear()
        try:
            asyncio.run(websocket_endpoint(websocket, rng.randrange(0, 2_147_483_647)))
        finally:
            manager.active_connections.clear()

        self.assertTrue(websocket.accepted)
        self.assertGreater(websocket.receive_calls, 15)
        self.assertEqual(len(websocket.sent), 2 * (websocket.receive_calls - 1))
