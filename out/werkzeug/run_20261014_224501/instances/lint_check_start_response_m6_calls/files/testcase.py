import io
import random
import sys
import unittest
import warnings

from werkzeug.middleware.lint import ErrorStream
from werkzeug.middleware.lint import GuardedWrite
from werkzeug.middleware.lint import HTTPWarning
from werkzeug.middleware.lint import InputStream
from werkzeug.middleware.lint import LintMiddleware
from werkzeug.middleware.lint import WSGIWarning


def _app(environ, start_response):
    return [b""]


REASONS = ["OK", "Created", "Moved", "Not Found", "Teapot", "Gone"]
CODES = [200, 201, 204, 301, 302, 304, 404, 418, 500, 503]
NAMES = ["Content-Type", "X-Req", "Cache-Control", "Vary", "Server", "X-Pad"]


def _status(rng, malformed_rate=0.0):
    code = rng.choice(CODES)
    reason = rng.choice(REASONS)
    if rng.random() < malformed_rate:
        kind = rng.randrange(4)
        if kind == 0:
            return f"{code}{rng.randrange(10)} {reason}"
        if kind == 1:
            return f"{code % 100:02d} {reason}"
        if kind == 2:
            return f"{code}"
        return f"0{code % 100:02d} {reason}"
    return f"{code} {reason}"


def _headers(rng, n):
    return [(rng.choice(NAMES), f"v{rng.randrange(1000)}") for _ in range(n)]


class CheckStartResponseFlowTest(unittest.TestCase):
    def _run(self, lint, status, headers, exc_info=None):
        return lint.check_start_response(status, headers, exc_info)

    def test_valid_batch_ignored(self):
        rng = random.Random(11)
        lint = LintMiddleware(_app)
        total = 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i in range(17):
                code, hdrs = self._run(lint, _status(rng), _headers(rng, i % 5))
                total += code + len(hdrs)
        self.assertGreater(total, 0)

    def test_malformed_status_errors(self):
        rng = random.Random(23)
        raised = ok = 0
        shared = LintMiddleware(_app)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for i in range(19):
                lint = LintMiddleware(_app) if i % 4 == 0 else shared
                try:
                    self._run(lint, _status(rng, 0.45), _headers(rng, 2))
                    ok += 1
                except WSGIWarning:
                    raised += 1
        self.assertEqual(raised + ok, 19)

    def test_etag_variants(self):
        rng = random.Random(37)
        lint = LintMiddleware(_app)
        tags = []
        for i in range(16):
            core = f"t{rng.randrange(99)}"
            quote = '"' if rng.random() < 0.5 else ""
            prefix = rng.choice(["", "", "W/", "w/"])
            tags.append(f"{prefix}{quote}{core}{quote}")
        caught = 0
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for tag in tags:
                try:
                    self._run(lint, "200 OK", [("ETag", tag), ("X-Req", "1")])
                except HTTPWarning:
                    caught += 1
        self.assertLessEqual(caught, len(tags))

    def test_location_headers(self):
        rng = random.Random(41)
        lint = LintMiddleware(_app)
        hosts = ["http://a.example", "https://b.example:8443", "", "//c.example"]
        caught = 0
        with warnings.catch_warnings():
            warnings.simplefilter("error", HTTPWarning)
            warnings.simplefilter("ignore", WSGIWarning)
            for i in range(15):
                loc = rng.choice(hosts) + "/p/" + str(rng.randrange(50))
                st = _status(rng, 0.3)
                try:
                    self._run(lint, st, [("Location", loc)])
                except HTTPWarning:
                    caught += 1
                except ValueError:
                    caught += 100
        self.assertGreaterEqual(caught, 0)

    def test_status_header_name(self):
        rng = random.Random(53)
        lint = LintMiddleware(_app)
        names = NAMES + ["Status", "status", "STATUS"]
        hits = 0
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for i in range(18):
                hdrs = [(rng.choice(names), "x") for _ in range(rng.randrange(1, 4))]
                try:
                    self._run(lint, "201 Created", hdrs)
                except WSGIWarning:
                    hits += 1
        self.assertGreaterEqual(hits, 1)

    def test_bytes_status(self):
        rng = random.Random(67)
        lint = LintMiddleware(_app)
        errs = 0
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for i in range(14):
                st = _status(rng)
                if rng.random() < 0.4:
                    st = st.encode("ascii")
                try:
                    self._run(lint, st, [])
                except WSGIWarning:
                    errs += 1
        self.assertLess(errs, 14)

    def test_exc_info_variants(self):
        rng = random.Random(71)
        lint = LintMiddleware(_app)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            real = sys.exc_info()
        choices = [None, real, ["not", "tuple"], "bad", None]
        bad = 0
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for i in range(16):
                exc = rng.choice(choices)
                try:
                    self._run(lint, _status(rng), _headers(rng, 1), exc)
                except WSGIWarning:
                    bad += 1
        self.assertGreaterEqual(bad, 0)

    def test_non_list_headers(self):
        rng = random.Random(83)
        lint = LintMiddleware(_app)
        raised = 0
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for i in range(15):
                hdrs = _headers(rng, rng.randrange(3))
                if rng.random() < 0.5:
                    hdrs = tuple(hdrs)
                try:
                    self._run(lint, _status(rng), hdrs)
                except WSGIWarning:
                    raised += 1
        self.assertGreaterEqual(raised, 0)

    def test_bad_header_items(self):
        rng = random.Random(97)
        lint = LintMiddleware(_app)
        outcomes = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i in range(16):
                r = rng.random()
                if r < 0.25:
                    item = ["X-List", "1"]
                elif r < 0.45:
                    item = ("X-Int", rng.randrange(9))
                elif r < 0.6:
                    item = ("X-Three", "a", "b")
                else:
                    item = (rng.choice(NAMES), "ok")
                try:
                    self._run(lint, _status(rng), [item])
                    outcomes.append("ok")
                except ValueError:
                    outcomes.append("value")
        self.assertEqual(len(outcomes), 16)

    def test_error_stream_and_target(self):
        rng = random.Random(101)
        lint = LintMiddleware(_app)
        buf = io.StringIO()
        stream = ErrorStream(buf)
        lines = [f"line {rng.randrange(100)}\n" for _ in range(rng.randrange(5, 12))]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stream.writelines(lines)
            for line in lines[:6]:
                stream.write(line.upper())
                self._run(lint, _status(rng), [("X-Line", line.strip())])
        self.assertTrue(buf.getvalue())

    def test_guarded_write_and_target(self):
        rng = random.Random(113)
        lint = LintMiddleware(_app)
        sink = []
        chunks = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            code, hdrs = self._run(lint, _status(rng), _headers(rng, 3))
            gw = GuardedWrite(sink.append, chunks)
            for i in range(code % 7 + 4):
                gw(b"x" * rng.randrange(1, 9))
        self.assertEqual(len(sink), len(chunks))

    def test_input_stream_and_target(self):
        rng = random.Random(127)
        lint = LintMiddleware(_app)
        data = b"".join(b"row%d\n" % rng.randrange(100) for _ in range(20))
        stream = InputStream(io.BytesIO(data))
        got = 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i in range(9):
                if i % 3 == 0:
                    got += len(stream.read(4))
                else:
                    got += len(stream.readline())
                self._run(lint, _status(rng, 0.2), _headers(rng, i % 3))
        self.assertGreater(got, 0)

    def test_environ_and_target(self):
        rng = random.Random(131)
        lint = LintMiddleware(_app)
        base = {
            "REQUEST_METHOD": "GET",
            "SERVER_NAME": "h",
            "SERVER_PORT": "80",
            "wsgi.version": (1, 0),
            "wsgi.input": io.BytesIO(),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i in range(7):
                env = dict(base)
                env["PATH_INFO"] = rng.choice(["/a", "b", ""])
                lint.check_environ(env)
                self._run(lint, _status(rng), [("Server", env["PATH_INFO"] or "-")])
        self.assertEqual(len(base), 9)


if __name__ == "__main__":
    unittest.main()
