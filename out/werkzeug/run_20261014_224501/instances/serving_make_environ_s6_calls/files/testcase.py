import random
import socket
import unittest

from werkzeug.serving import BaseWSGIServer


class _PeerSocket(socket.socket):
    """Socket whose getpeercert() behaviour is chosen per connection."""

    peer_mode = "none"

    def getpeercert(self, binary_form=False):
        if self.peer_mode == "handshake":
            raise ValueError("handshake not done")
        if self.peer_mode == "cert":
            return bytes(range(48))
        return None


_TE_POOL = [
    "chunked",
    "gzip",
    '"chunked"',
    " ",
    "deflate, chunked",
    '"a,b", br',
    "Chunked",
    '"open, chunked',
    "identity,,compress",
    'x\\"y, "q\\"z"',
]


def _build_requests():
    rng = random.Random(4242)
    specs = []
    for idx in range(12):
        segs = [rng.choice(["a", "b%20c", "%7Ex", "d", "e%2Ff"]) for _ in range(rng.randint(1, 3))]
        prefix = "/" if rng.random() < 0.7 else "//"
        path = prefix + "/".join(segs)
        if rng.random() < 0.5:
            path += "?q=" + str(rng.randint(0, 99))
        headers = [("Host", "example.test"), ("X-Idx", str(idx))]
        for _ in range(rng.randint(0, 3)):
            name = "Transfer-Encoding" if rng.random() < 0.8 else "Transfer_Encoding"
            headers.append((name, rng.choice(_TE_POOL)))
        mode = rng.choice(["plain", "none", "handshake", "cert"])
        addr_kind = rng.choice(["tuple", "str", "empty"])
        specs.append((path, headers, mode, addr_kind))
    return specs


def _app(environ, start_response):
    body = "|".join(
        [
            environ["PATH_INFO"],
            str("wsgi.input_terminated" in environ),
            str("SSL_CLIENT_CERT" in environ),
            str(environ["REMOTE_PORT"]),
        ]
    ).encode("latin1")
    start_response("200 OK", [("Content-Length", str(len(body)))])
    return [body]


class TestServingRequestCycle(unittest.TestCase):
    def setUp(self):
        self.server = BaseWSGIServer("127.0.0.1", 0, _app)

    def tearDown(self):
        self.server.server_close()

    def _roundtrip(self, path, headers, mode, addr_kind, idx):
        srv_sock, cli_sock = socket.socketpair()
        if mode != "plain":
            fam, typ, proto = srv_sock.family, srv_sock.type, srv_sock.proto
            peer = _PeerSocket(fam, typ, proto, fileno=srv_sock.detach())
            peer.peer_mode = mode
            srv_sock = peer
        raw = f"GET {path} HTTP/1.0\r\n"
        raw += "".join(f"{k}: {v}\r\n" for k, v in headers)
        raw += "\r\n"
        cli_sock.sendall(raw.encode("latin1"))
        cli_sock.shutdown(socket.SHUT_WR)
        if addr_kind == "tuple":
            address = ("10.0.0.%d" % (idx + 1), 40000 + idx)
        elif addr_kind == "str":
            address = "peer-%d" % idx
        else:
            address = ""
        self.server.process_request(srv_sock, address)
        chunks = []
        while True:
            data = cli_sock.recv(65536)
            if not data:
                break
            chunks.append(data)
        cli_sock.close()
        return b"".join(chunks)

    def test_sequence_of_requests(self):
        specs = _build_requests()
        responses = [
            self._roundtrip(path, headers, mode, kind, idx)
            for idx, (path, headers, mode, kind) in enumerate(specs)
        ]
        self.assertEqual(len(responses), len(specs))
        for resp in responses:
            self.assertTrue(resp.startswith(b"HTTP/1.0 200"), resp[:40])
            self.assertEqual(resp.split(b"\r\n\r\n", 1)[1].count(b"|"), 3)
