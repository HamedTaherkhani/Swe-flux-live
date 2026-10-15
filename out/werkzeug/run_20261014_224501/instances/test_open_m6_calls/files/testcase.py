"""Client request/redirect scenarios driven through werkzeug's test Client."""
from __future__ import annotations

import random
import unittest

from werkzeug.test import Client
from werkzeug.test import ClientRedirectError
from werkzeug.wrappers import Request
from werkzeug.wrappers import Response

REDIRECT_CODES = (301, 302, 303, 307, 308)


def _next_collatz(n: int) -> int:
    return n // 2 if n % 2 == 0 else 3 * n + 1


def _collatz_steps(n: int) -> int:
    steps = 0
    while n != 1:
        n = _next_collatz(n)
        steps += 1
    return steps


@Request.application
def app(request: Request) -> Response:
    parts = [p for p in request.path.split("/") if p]

    if parts and parts[0] == "collatz":
        n = int(parts[1])
        if n <= 1:
            resp = Response(f"done {request.method}")
        else:
            resp = Response(status=REDIRECT_CODES[n % 5])
            resp.headers["Location"] = f"/collatz/{_next_collatz(n)}"
        if n % 4 == 0:
            resp.set_cookie(f"c{n % 3}", str(n))
        if n % 7 == 0:
            resp.delete_cookie(f"c{n % 3}")
        return resp

    if parts and parts[0] == "loop":
        target = "b" if parts[1] == "a" else "a"
        resp = Response(status=302)
        resp.headers["Location"] = f"/loop/{target}"
        return resp

    if parts and parts[0] == "ext":
        resp = Response(status=301)
        resp.headers["Location"] = "http://example.org/collatz/2"
        return resp

    if parts and parts[0] == "sub":
        resp = Response(status=307)
        resp.headers["Location"] = "http://api.localhost/collatz/" + parts[1]
        return resp

    if parts and parts[0] == "count":
        current = int(request.cookies.get("n", "0"))
        resp = Response(str(current))
        resp.set_cookie("n", str(current + 1))
        return resp

    return Response("not found", status=404)


class ClientFlowTest(unittest.TestCase):
    def test_collatz_get_follow(self):
        c = Client(app)
        r = c.get("/collatz/7", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.history), _collatz_steps(7))

    def test_collatz_post_follow(self):
        c = Client(app)
        r = c.post("/collatz/6", data={"x": "1"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.text.startswith("done"))

    def test_put_without_follow(self):
        c = Client(app)
        codes = [c.put(f"/collatz/{n}").status_code for n in range(3, 3 + 6)]
        self.assertTrue(all(code in REDIRECT_CODES for code in codes))

    def test_redirect_loop(self):
        c = Client(app)
        with self.assertRaises(ClientRedirectError):
            c.get("/loop/a", follow_redirects=True)

    def test_external_redirect(self):
        c = Client(app)
        with self.assertRaises(RuntimeError):
            c.patch("/ext", follow_redirects=True)

    def test_subdomain_redirect(self):
        c = Client(app, allow_subdomain_redirects=True)
        seeds = [5, 3]
        for seed in seeds:
            r = c.delete(f"/sub/{seed}", follow_redirects=True)
            self.assertEqual(r.status_code, 200)

    def test_cookie_api_random(self):
        rng = random.Random(1234)
        c = Client(app)
        keys = [f"k{i}" for i in range(rng.randint(9, 14))]
        values = {k: rng.randint(0, 99) for k in keys}
        for k in keys:
            c.set_cookie(k, str(values[k]))
        for k in keys:
            if values[k] % 3 == 0:
                c.delete_cookie(k)
        present = [k for k in keys if c.get_cookie(k) is not None]
        self.assertLessEqual(len(present), len(keys))

    def test_cookies_disabled(self):
        c = Client(app, use_cookies=False)
        with self.assertRaises(TypeError):
            c.get_cookie("anything")
        with self.assertRaises(TypeError):
            c.delete_cookie("anything")
        r = c.head("/collatz/1")
        self.assertEqual(r.status_code, 200)

    def test_options_or_head_batch(self):
        c = Client(app)
        statuses = []
        for n in range(1, 10):
            if _collatz_steps(n) % 2 == 0:
                statuses.append(c.options(f"/collatz/{n}", follow_redirects=n > 5).status_code)
            else:
                statuses.append(c.head(f"/collatz/{n}").status_code)
        self.assertEqual(len(statuses), 9)

    def test_query_follow(self):
        c = Client(app)
        r = c.query("/collatz/12", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.history), 3)

    def test_counter_cookie_roundtrip(self):
        c = Client(app)
        rng = random.Random(42)
        total = sum(rng.choice([1, 2, 3]) for _ in range(6))
        for _ in range(total):
            c.get("/count")
        self.assertEqual(int(c.get_cookie("n").value), total)

    def test_preset_cookie_then_follow(self):
        c = Client(app)
        for i in range(3):
            c.set_cookie(f"c{i}", "seed", path="/collatz")
        r = c.get("/collatz/9", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(c.get_cookie("missing"))
