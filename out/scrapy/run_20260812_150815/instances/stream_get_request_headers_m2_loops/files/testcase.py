import random
import sys
import unittest
from types import SimpleNamespace
from types import ModuleType


if "h2" not in sys.modules:
    h2_module = ModuleType("h2")
    h2_errors = ModuleType("h2.errors")
    h2_exceptions = ModuleType("h2.exceptions")

    class _H2Error(Exception):
        pass

    h2_errors.ErrorCodes = SimpleNamespace(CANCEL=0, NO_ERROR=1)
    h2_exceptions.H2Error = _H2Error
    h2_exceptions.ProtocolError = type("ProtocolError", (_H2Error,), {})
    h2_exceptions.StreamClosedError = type("StreamClosedError", (_H2Error,), {})
    sys.modules["h2"] = h2_module
    sys.modules["h2.errors"] = h2_errors
    sys.modules["h2.exceptions"] = h2_exceptions

from scrapy.core.http2.stream import Stream
from scrapy.http import Headers, Request


class _RecordingConnection:
    max_outbound_frame_size = 1 << 14

    def __init__(self) -> None:
        self.header_blocks = []
        self.data_frames = []
        self.ended_streams = []

    def send_headers(self, stream_id, headers, end_stream=False) -> None:
        self.header_blocks.append((stream_id, headers, end_stream))

    def local_flow_control_window(self, stream_id) -> int:
        return (stream_id << 9) + (1 << 15)

    def send_data(self, stream_id, data, end_stream=False) -> None:
        self.data_frames.append((stream_id, data, end_stream))

    def end_stream(self, stream_id) -> None:
        self.ended_streams.append(stream_id)


class TestStreamRequestHeaderLoops(unittest.TestCase):
    def _exercise(
        self,
        token: str,
        method: str,
        path_mode: str,
        body_mode: int,
        length_mode: str,
    ) -> None:
        generator = random.Random(f"header-matrix:{token}")
        name_count = (
            len(token)
            + sum((index + 1) * ord(char) for index, char in enumerate(token))
        ) % (len(token) + 17) + 4
        header_pairs = []
        for index in range(name_count):
            value_count = 1 + generator.randrange(1 + (index + body_mode) % 5)
            values = [
                f"{token[::-1]}-{index:x}-{generator.getrandbits(28):07x}-{slot}"
                for slot in range(value_count)
            ]
            header_pairs.append((f"X-Matrix-{token}-{index:x}", values))

        body_size = (
            sum(generator.randrange(1, ord(char) + 1) for char in token)
            * (body_mode + 1)
        ) % (1 << 13)
        body = bytes(
            (generator.randrange(256) ^ (offset * (body_mode + 3))) & 0xFF
            for offset in range(body_size)
        )
        if length_mode != "absent":
            declared = len(body)
            if length_mode == "mixed":
                supplied = [
                    str(declared + ((position % 3) - 1) * (body_mode + 1))
                    for position in range(1 + len(token) % 4)
                ]
            else:
                supplied = [str(declared)]
            header_pairs.insert(generator.randrange(len(header_pairs) + 1), ("content-length", supplied))

        if path_mode == "root":
            url = "https://qa.invalid"
        elif path_mode == "query":
            query = "&".join(
                f"k{index:x}={generator.getrandbits(20):x}"
                for index in range(1 + body_mode % 6)
            )
            url = f"https://qa.invalid/{token[::-1]}?{query}"
        else:
            segments = [
                f"{char}{generator.randrange(ord(char) + 1):x}" for char in token
            ]
            url = "https://qa.invalid/" + "/".join(segments)

        request = Request(
            url,
            method=method,
            headers=Headers(header_pairs),
            body=body,
        )
        connection = _RecordingConnection()
        protocol = SimpleNamespace(
            conn=connection,
            metadata={
                "uri": SimpleNamespace(
                    scheme="https",
                    host=b"qa.invalid",
                    netloc=b"qa.invalid",
                    port=443,
                ),
                "ip_address": "192.0.2.73",
            },
        )
        stream_id = 1 + 2 * generator.randrange(1, 1 << 8)
        stream = Stream(stream_id, request, protocol, SimpleNamespace())

        stream.initiate_request()

        self.assertTrue(stream.metadata["request_sent"])
        self.assertEqual(len(connection.header_blocks), 1)
        self.assertEqual(connection.header_blocks[0][0], stream_id)
        self.assertFalse(connection.header_blocks[0][2])
        self.assertEqual(connection.ended_streams, [stream_id])
        self.assertEqual(
            sum(len(frame[1]) for frame in connection.data_frames), len(body)
        )

    def test_options_root_with_mixed_length(self) -> None:
        self._exercise("amber", "OPTIONS", "root", 2, "mixed")

    def test_connect_with_absent_length(self) -> None:
        self._exercise("beryl", "CONNECT", "segments", 5, "absent")

    def test_post_query_with_exact_length(self) -> None:
        self._exercise("citrine", "POST", "query", 7, "exact")

    def test_get_segmented_without_length(self) -> None:
        self._exercise("dahlia", "GET", "segments", 1, "absent")

    def test_patch_query_with_mixed_length(self) -> None:
        self._exercise("elm", "PATCH", "query", 8, "mixed")

    def test_put_root_with_exact_length(self) -> None:
        self._exercise("fuchsia", "PUT", "root", 3, "exact")

    def test_delete_segmented_with_mixed_length(self) -> None:
        self._exercise("garnet", "DELETE", "segments", 6, "mixed")

    def test_head_query_without_length(self) -> None:
        self._exercise("heliotrope", "HEAD", "query", 4, "absent")

    def test_trace_segmented_with_exact_length(self) -> None:
        self._exercise("indigo", "TRACE", "segments", 9, "exact")

    def test_options_query_without_length(self) -> None:
        self._exercise("juniper", "OPTIONS", "query", 0, "absent")

    def test_post_root_with_mixed_length(self) -> None:
        self._exercise("kestrel", "POST", "root", 10, "mixed")

    def test_connect_query_with_exact_length(self) -> None:
        self._exercise(
            "lilac", "CONNECT", "query", len("orchidarium"), "exact"
        )
