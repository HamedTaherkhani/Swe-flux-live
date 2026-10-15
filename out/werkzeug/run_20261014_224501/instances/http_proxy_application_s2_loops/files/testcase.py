import random
import unittest
from unittest import mock

from werkzeug.middleware import http_proxy
from werkzeug.middleware.http_proxy import ProxyMiddleware
from werkzeug.test import create_environ


class _FakeResponse:
    def __init__(self, seed):
        self.status = 200 + seed % 3
        rng = random.Random(seed)
        self._headers = [("Content-Type", "text/plain"), ("Connection", "x-up-a")]
        for i in range(rng.randint(4, 9)):
            self._headers.append((rng.choice(["X-Up-A", "X-Up-B", "Keep-Alive"]), str(i)))

    def getheaders(self):
        return list(self._headers)

    def __iter__(self):
        yield b"proxied"

    def close(self):
        pass


class _FakeConnection:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.sent_headers = []
        self.sent_bytes = 0
        self.url = None
        _FakeConnection.instances.append(self)

    def connect(self):
        pass

    def putrequest(self, method, url, skip_host=False):
        self.method = method
        self.url = url

    def putheader(self, key, value):
        self.sent_headers.append((key, value))

    def endheaders(self):
        pass

    def send(self, data):
        self.sent_bytes += len(data)

    def getresponse(self):
        return _FakeResponse(len(self.sent_headers) + self.sent_bytes)


class _JitteryInput:
    """A terminated input stream that hands out pieces of varying size."""

    def __init__(self, payload, seed):
        self._data = payload
        self._pos = 0
        self._rng = random.Random(seed)

    def read(self, size=-1):
        if self._pos >= len(self._data):
            return b""
        step = self._rng.randint(1, max(1, size))
        if size < 0:
            step = len(self._data)
        chunk = self._data[self._pos : self._pos + step]
        self._pos += len(chunk)
        return chunk


def _build_environ(rng, idx):
    words = ["alpha", "beta", "gamma", "delta", "omega", "sigma"]
    payload = bytes(rng.randrange(256) for _ in range(rng.randint(150, 260)))
    env = create_environ(
        path=f"/api/v{idx}/" + "/".join(rng.sample(words, 3)),
        method=rng.choice(["POST", "PUT"]),
        query_string=f"page={rng.randint(1, 9)}&q={rng.choice(words)}",
        headers=None,
    )
    env["wsgi.input"] = _JitteryInput(payload, seed=idx * 31 + 7)
    env["wsgi.input_terminated"] = True
    env["CONTENT_TYPE"] = "application/octet-stream"
    env["HTTP_HOST"] = f"client{idx}.example"
    names = [f"X-Gen-{i}" for i in range(rng.randint(14, 22))]
    for name in names:
        env["HTTP_" + name.upper().replace("-", "_")] = rng.choice(words)
    for name in ("Keep-Alive", "Te", "Upgrade", "Proxy-Connection"):
        if rng.random() < 0.6:
            env["HTTP_" + name.upper().replace("-", "_")] = "1"
    dropped = rng.sample(names, 4) + ["x-not-present"]
    env["HTTP_CONNECTION"] = ", ".join(n.lower() if i % 2 else n for i, n in enumerate(dropped))
    return env


class TestProxyApplicationLoops(unittest.TestCase):
    def test_header_and_body_forwarding(self):
        rng = random.Random(7351913)
        variants = [
            {"target": "http://upstream.local:8081/base/", "remove_prefix": True},
            {
                "target": "https://secure.local/root",
                "host": None,
                "headers": {
                    "X-Gen-3": ["dup-a", "dup-b"],
                    "X-Extra": ("e1", "e2", "e3"),
                    "Host": "override.local",
                },
            },
            {"target": "http://plain.local/", "host": "fixed.local", "headers": [("X-Tail", "t")]},
        ]
        mw = ProxyMiddleware(lambda e, s: [b"app"], {"/api/": variants[0]}, chunk_size=24)
        statuses = []
        _FakeConnection.instances.clear()
        with mock.patch.object(http_proxy.client, "HTTPConnection", _FakeConnection), \
                mock.patch.object(http_proxy.client, "HTTPSConnection", _FakeConnection):
            for idx, opts in enumerate(variants, start=1):
                full = mw.targets["/api/"] if idx == 1 else {
                    "remove_prefix": False, "host": "<auto>", "headers": {},
                    "ssl_context": None, **opts,
                }
                env = _build_environ(rng, idx)
                app = mw.proxy_to(full, env["PATH_INFO"], "/api/")
                body = b"".join(app(env, lambda status, headers: statuses.append(status)))
                self.assertEqual(body, b"proxied")

        self.assertEqual(len(_FakeConnection.instances), 3)
        for con in _FakeConnection.instances:
            self.assertTrue(con.url.startswith("/"))
            self.assertGreater(con.sent_bytes, 100)
            self.assertIn("Connection", [k for k, _ in con.sent_headers])
        self.assertEqual(len(statuses), 3)


if __name__ == "__main__":
    unittest.main()
