import random
import unittest
import warnings

from werkzeug.test import Client
from werkzeug.wrappers import Response

SYLLABLES = ["ka", "lo", "mi", "ne", "ru", "so", "ti", "va"]


class AbsoluteLocationResponse(Response):
    autocorrect_location_header = True


def _name(rng, n):
    return "".join(rng.choice(SYLLABLES) for _ in range(n))


def _extra_headers(seed, count):
    rng = random.Random(seed)
    out = []
    for i in range(count):
        key = "X-" + _name(rng, rng.randint(1, 3)).title()
        out.append((key, f"{i}-{rng.randint(100, 999)}"))
    return out


def _app_for(builder):
    def app(environ, start_response):
        response = builder(environ)
        return response(environ, start_response)

    return app


def _fetch(builder, path="/", method="GET"):
    client = Client(_app_for(builder))
    return client.open(path, method=method)


class WsgiHeaderMatrixTest(unittest.TestCase):
    def test_list_body_many_extra_headers(self):
        chunks = [_name(random.Random(k), k % 4 + 1).encode() for k in range(9)]

        def build(environ):
            r = Response(list(chunks), mimetype="text/plain")
            for k, v in _extra_headers(11, 14):
                r.headers.add(k, v)
            return r

        resp = _fetch(build)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(int(resp.headers["Content-Length"]), len(b"".join(chunks)))

    def test_generator_body_skips_length(self):
        def build(environ):
            gen = (str(i * i).encode() for i in range(6))
            r = Response(gen)
            for k, v in _extra_headers(23, 9):
                r.headers.add(k, v)
            return r

        resp = _fetch(build)
        self.assertNotIn("Content-Length", resp.headers)
        self.assertTrue(resp.get_data())

    def test_no_content_drops_length(self):
        def build(environ):
            r = Response("ignored body", status=204)
            for k, v in _extra_headers(5, 4):
                r.headers.add(k, v)
            return r

        resp = _fetch(build)
        self.assertEqual(resp.status_code, 204)
        self.assertNotIn("Content-Length", resp.headers)

    def test_informational_statuses(self):
        for offset, status in enumerate((100, 103, 199)):

            def build(environ, status=status, offset=offset):
                r = Response(b"x" * (offset + 1), status=status)
                for k, v in _extra_headers(40 + offset, offset + 2):
                    r.headers.add(k, v)
                return r

            resp = _fetch(build)
            self.assertNotIn("Content-Length", resp.headers)

    def test_not_modified_strips_metadata(self):
        def build(environ):
            r = Response("cached", status=304, content_type="text/html")
            r.headers["Content-Encoding"] = "gzip"
            r.headers["Content-Language"] = "de"
            r.headers["ETag"] = '"abc"'
            for k, v in _extra_headers(77, 6):
                r.headers.add(k, v)
            return r

        resp = _fetch(build)
        self.assertNotIn("Content-Type", resp.headers)
        self.assertIn("ETag", resp.headers)

    def test_ascii_relative_redirects(self):
        rng = random.Random(909)
        for i in range(4):
            target = "/" + "/".join(_name(rng, 2) for _ in range(i + 1))

            def build(environ, target=target, i=i):
                r = Response("moved", status=301 + i)
                r.headers["Location"] = target
                return r

            resp = _fetch(build)
            self.assertTrue(resp.headers["Location"].startswith("/"))

    def test_iri_location_warns(self):
        def build(environ):
            r = Response(["redirecting"], status=302)
            r.headers["Location"] = "/café/über?q=ä"
            r.headers.add("X-Trace", "1")
            return r

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resp = _fetch(build)
        self.assertTrue(caught)
        self.assertIn("%", resp.headers["Location"])

    def test_autocorrected_location(self):
        def build(environ):
            r = AbsoluteLocationResponse(["go"], status=303)
            r.headers["Location"] = "../next/step"
            for k, v in _extra_headers(13, 3):
                r.headers.add(k, v)
            return r

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            resp = _fetch(build, path="/a/b/c")
        self.assertTrue(resp.headers["Location"].startswith("http"))

    def test_content_location_ascii(self):
        def build(environ):
            r = Response([b"one", b"two"])
            r.headers["Content-Location"] = "/docs/item.json"
            for k, v in _extra_headers(31, 5):
                r.headers.add(k, v)
            return r

        resp = _fetch(build)
        self.assertIn("Content-Location", resp.headers)
        self.assertIn("Content-Length", resp.headers)

    def test_explicit_length_with_list_body(self):
        def build(environ):
            body = [b"ab", b"cd", b"ef"]
            r = Response(body)
            r.headers["Content-Length"] = str(sum(map(len, body)))
            return r

        resp = _fetch(build)
        self.assertEqual(resp.get_data(), b"abcdef")

    def test_head_requests_with_string_bodies(self):
        for n in range(3):

            def build(environ, n=n):
                r = Response("z" * (n + 2) * 3)
                for k, v in _extra_headers(60 + n, 2 * n + 1):
                    r.headers.add(k, v)
                return r

            resp = _fetch(build, method="HEAD")
            self.assertEqual(resp.get_data(), b"")

    def test_mixed_status_batch(self):
        rng = random.Random(2024)
        statuses = [rng.choice([200, 204, 304, 404, 102]) for _ in range(7)]
        for i, status in enumerate(statuses):

            def build(environ, status=status, i=i):
                body = [b"q"] * (i + 1) if i % 2 else (b"r" for _ in range(i + 1))
                r = Response(body, status=status)
                if i % 3 == 0:
                    r.headers["Content-Location"] = f"/v{i}"
                for k, v in _extra_headers(500 + i, i % 4):
                    r.headers.add(k, v)
                return r

            resp = _fetch(build)
            self.assertEqual(resp.status_code, status)
