import random
import unittest

from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map
from werkzeug.routing import Rule
from werkzeug.test import Client
from werkzeug.wrappers import Request
from werkzeug.wrappers import Response

SECTIONS = ["news", "shop", "wiki", "blog", "docs", "media"]


def _legacy_target(adapter, **values):
    # Only knows how to forward a handful of ids.
    table = {n: f"/items/{n * 3}" for n in range(0, 40, 4)}
    return table[values["n"]]


def build_map():
    rules = []
    for idx, sec in enumerate(SECTIONS):
        rules.append(Rule(f"/{sec}/", endpoint=f"{sec}.index"))
        rules.append(
            Rule(
                f"/{sec}/<int:page>",
                endpoint=f"{sec}.page",
                methods=["GET"] if idx % 2 else ["GET", "POST"],
            )
        )
        rules.append(
            Rule(f"/{sec}/p<int:page>", endpoint=f"{sec}.page", alias=True)
        )
        if idx % 3 == 0:
            rules.append(
                Rule(f"/{sec}/raw/<path:rest>", endpoint=f"{sec}.raw", strict_slashes=False)
            )
    rules.append(Rule("/items/<int:n>", endpoint="items.show"))
    rules.append(Rule("/old/<int:n>", redirect_to=_legacy_target))
    rules.append(Rule("/moved/<int:n>", redirect_to="items/<n>"))
    rules.append(Rule("/live", endpoint="live", websocket=True))
    return Map(rules, redirect_defaults=False, merge_slashes=True)


def plan_paths(rng, count):
    paths = []
    for i in range(count):
        sec = SECTIONS[rng.randrange(len(SECTIONS))]
        kind = (i * 7 + rng.randrange(5)) % 9
        num = rng.randrange(1, 60)
        if kind == 0:
            paths.append((f"/{sec}", "GET"))
        elif kind == 1:
            paths.append((f"/{sec}/{num}", "POST" if num % 2 else "GET"))
        elif kind == 2:
            paths.append((f"/{sec}/p{num}", "GET"))
        elif kind == 3:
            paths.append((f"/{sec}//{num}", "GET"))
        elif kind == 4:
            paths.append((f"/old/{num}", "GET"))
        elif kind == 5:
            paths.append((f"/moved/{num}", "GET"))
        elif kind == 6:
            paths.append((f"/{sec}/raw/a/{num}/", "GET"))
        elif kind == 7:
            paths.append(("/live", "GET"))
        else:
            paths.append((f"/{sec}/x{num}", "DELETE"))
    return paths


class RoutingDispatchTest(unittest.TestCase):
    def test_dispatch_matrix(self):
        url_map = build_map()
        rng = random.Random(9173)
        paths = plan_paths(rng, 36)

        def app(environ, start_response):
            request = Request(environ)
            urls = url_map.bind_to_environ(environ)

            def view(endpoint, values):
                return Response(f"{endpoint}:{sorted(values.items())}")

            try:
                rv = urls.dispatch(view, catch_http_exceptions=True)
            except Exception as e:  # noqa: BLE001
                rv = Response(type(e).__name__, status=599)
            if isinstance(rv, HTTPException):
                rv = rv.get_response(request.environ)
            return rv(environ, start_response)

        client = Client(app)
        statuses = []
        for path, method in paths:
            resp = client.open(path, method=method)
            statuses.append(resp.status_code)
            resp.close()

        adapter = url_map.bind("example.org", "/")
        reachable = 0
        for p, m in paths[::3]:
            try:
                reachable += adapter.test(p, m)
            except Exception:  # noqa: BLE001
                reachable -= 1
        allowed = []
        for p, _ in paths[1::4]:
            try:
                allowed.append(sorted(adapter.allowed_methods(p)))
            except Exception:  # noqa: BLE001
                allowed.append([])

        self.assertEqual(len(statuses), len(paths))
        self.assertGreater(len(set(statuses)), 3)
        self.assertTrue(abs(reachable) <= len(paths[::3]))
        self.assertTrue(all(isinstance(a, list) for a in allowed))
