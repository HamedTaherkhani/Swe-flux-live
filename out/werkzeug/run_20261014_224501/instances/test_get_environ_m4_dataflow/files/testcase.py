import io
import random
import unittest

from werkzeug.datastructures import Headers
from werkzeug.test import Client
from werkzeug.test import create_environ
from werkzeug.wrappers import Request
from werkzeug.wrappers import Response

SYLLABLES = ["ba", "do", "ki", "lu", "me", "no", "pa", "ri", "su", "te"]


def _word(rng, n):
    return "".join(rng.choice(SYLLABLES) for _ in range(n))


def _header_list(seed, count, pool):
    """Generate ``count`` headers whose names are drawn from a small pool,
    so some names repeat and get combined."""
    rng = random.Random(seed)
    names = ["X-" + _word(rng, rng.randint(1, 2)).title() for _ in range(pool)]
    return [(rng.choice(names), _word(rng, 3)) for _ in range(count)]


def _form_data(seed, count):
    rng = random.Random(seed)
    return {_word(rng, 2) + str(i): _word(rng, rng.randint(1, 4)) for i in range(count)}


def _app(request_environ):
    request = Request(request_environ)
    path = request.path
    if path.startswith("/hop/"):
        remaining, _, code = path[len("/hop/") :].partition("/")
        remaining = int(remaining)
        if remaining > 0:
            target = f"/hop/{remaining - 1}/{code}"
            return Response("", status=int(code), headers={"Location": target})
    body = f"{request.method}:{len(request.get_data())}:{len(request.headers)}"
    return Response(body)


def _wsgi(environ, start_response):
    return _app(environ)(environ, start_response)


def _client():
    return Client(_wsgi, use_cookies=False)


class EnvironBuilderFlowTest(unittest.TestCase):
    def test_plain_get_with_generated_headers(self):
        headers = _header_list(11, 9, 4)
        resp = _client().get("/plain", headers=headers)
        method, size, _ = resp.get_data(as_text=True).split(":")
        self.assertEqual(method, "GET")
        self.assertEqual(int(size), 0)

    def test_raw_bytes_body(self):
        rng = random.Random(23)
        payload = bytes(rng.randrange(256) for _ in range(rng.randint(40, 90)))
        resp = _client().put("/raw", data=payload, headers=_header_list(23, 5, 2))
        self.assertEqual(int(resp.get_data(as_text=True).split(":")[1]), len(payload))

    def test_urlencoded_form(self):
        data = _form_data(31, 7)
        resp = _client().post("/form", data=data, headers=_header_list(31, 3, 3))
        self.assertTrue(resp.get_data(as_text=True).startswith("POST:"))

    def test_multipart_with_files(self):
        rng = random.Random(41)
        data = _form_data(41, 4)
        for i in range(3):
            blob = bytes(rng.randrange(256) for _ in range(rng.randint(5, 30)))
            data[f"file{i}"] = (io.BytesIO(blob), f"f{i}.bin")
        resp = _client().post("/upload", data=data)
        self.assertGreater(int(resp.get_data(as_text=True).split(":")[1]), 0)

    def test_redirect_chain_post_302_drops_body(self):
        data = _form_data(53, 5)
        resp = _client().post(
            "/hop/3/302", data=data, follow_redirects=True,
            headers=_header_list(53, 4, 2),
        )
        self.assertEqual(len(resp.history), 3)
        self.assertTrue(resp.get_data(as_text=True).startswith("GET:0:"))

    def test_redirect_chain_307_keeps_stream(self):
        rng = random.Random(59)
        payload = "".join(rng.choice("abcdef") for _ in range(rng.randint(20, 50)))
        resp = _client().post(
            "/hop/4/307", data=payload, follow_redirects=True,
            headers=_header_list(59, 6, 3),
        )
        self.assertEqual(len(resp.history), 4)
        self.assertTrue(resp.get_data(as_text=True).startswith("POST:"))

    def test_environ_base_and_overrides(self):
        environ = create_environ(
            "/base",
            environ_base={"REMOTE_ADDR": "10.0.0.7", "HTTP_X_BASE": "b"},
            environ_overrides={"SERVER_PORT": "8081"},
            headers=_header_list(67, 7, 5),
        )
        self.assertEqual(environ["SERVER_PORT"], "8081")
        self.assertEqual(environ["REMOTE_ADDR"], "10.0.0.7")

    def test_json_body_via_builder_arg(self):
        rng = random.Random(71)
        doc = {_word(rng, 2): rng.randint(0, 99) for _ in range(6)}
        resp = _client().patch("/json", json=doc, headers=_header_list(71, 2, 2))
        self.assertTrue(resp.get_data(as_text=True).startswith("PATCH:"))

    def test_explicit_content_type_no_body(self):
        environ = create_environ(
            "/ct", method="DELETE", content_type="text/plain; charset=utf-8"
        )
        self.assertEqual(environ["REQUEST_METHOD"], "DELETE")
        self.assertIn("CONTENT_TYPE", environ)

    def test_repeated_header_names_merge(self):
        h = Headers()
        rng = random.Random(83)
        for i in range(12):
            h.add(rng.choice(["X-Alpha", "X-Beta", "X-Gamma"]), str(i * 7 % 13))
        environ = create_environ("/merge", headers=h)
        merged = [k for k in environ if k.startswith("HTTP_X_")]
        self.assertLessEqual(len(merged), 3)

    def test_redirect_303_put_with_form(self):
        data = _form_data(97, 3)
        resp = _client().put(
            "/hop/2/303", data=data, follow_redirects=True,
            headers=_header_list(97, 3, 1),
        )
        self.assertEqual(len(resp.history), 2)

    def test_stream_input_partially_read(self):
        rng = random.Random(101)
        raw = bytes(rng.randrange(256) for _ in range(64))
        stream = io.BytesIO(raw)
        stream.read(rng.randint(5, 20))
        environ = create_environ(
            "/stream", method="POST", input_stream=stream,
            headers=_header_list(101, 4, 4),
        )
        self.assertLess(int(environ["CONTENT_LENGTH"]), len(raw))
