import encodings.idna  # noqa: F401  (preload before sys.path is patched)
import random
import sys
import types
import unittest
import warnings
from unittest import mock

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from werkzeug import testapp


from werkzeug.test import EnvironBuilder

_MISSING = object()
_WORDS = ["alpha", "beta", "gamma", "delta", "omega", "sigma", "kappa", "zeta"]


class _Dist:
    def __init__(self, name, version, mode):
        self.project_name = name
        self._version = version
        self._mode = mode

    @property
    def version(self):
        if self._mode == 1:
            raise ValueError("bad version metadata")
        if self._mode == 2:
            raise AttributeError("no version")
        return self._version


def _fake_pkg_resources(rng, n):
    dists = []
    for i in range(n):
        name = rng.choice(_WORDS).capitalize() + "-" + str(rng.randint(0, 99))
        mode = rng.choice([0, 0, 0, 1, 2])
        dists.append(_Dist(name, f"{rng.randint(0, 9)}.{i}", mode))
    mod = types.ModuleType("pkg_resources")
    mod.working_set = dists
    return mod


def _fake_sys_path(rng, n):
    out = []
    for i in range(n):
        kind = rng.randint(0, 4)
        if kind == 0:
            out.append("")
        elif kind == 1:
            out.append(rng.choice(_WORDS) + "/" + rng.choice(_WORDS))
        elif kind == 2:
            out.append("/nonexistent/" + rng.choice(_WORDS) + str(i))
        elif kind == 3:
            out.append("/tmp")
        else:
            out.append("~/" + rng.choice(_WORDS))
    return out


def _headers(rng, n):
    hdrs = []
    for _ in range(n):
        name = "X-" + rng.choice(_WORDS[:4]).title()
        hdrs.append((name, str(rng.randint(0, 999))))
    return hdrs


class TestTestAppLoops(unittest.TestCase):
    def _run(self, seed, n_dists, n_path, n_headers, use_pkg=True, **kw):
        rng = random.Random(seed)
        pkg = _fake_pkg_resources(rng, n_dists) if use_pkg else None
        path = _fake_sys_path(rng, n_path)
        builder = EnvironBuilder(headers=_headers(rng, n_headers), **kw)
        environ = builder.get_environ()
        statuses = []

        def start_response(status, headers, exc_info=None):
            statuses.append(status)

        saved = sys.modules.get("pkg_resources", _MISSING)
        sys.modules["pkg_resources"] = pkg
        try:
            with mock.patch.object(sys, "path", path), mock.patch.object(
                testapp, "_werkzeug_version", "0.0.dev"
            ):
                body = b"".join(testapp.test_app(environ, start_response))
        finally:
            if saved is _MISSING:
                del sys.modules["pkg_resources"]
            else:
                sys.modules["pkg_resources"] = saved
        self.assertEqual(statuses, ["200 OK"])
        self.assertIn(b"WSGI Information", body)
        self.assertEqual(body.count(b"<tr><th>"), len(environ))
        return body

    def test_plain_get(self):
        self._run(11, 7, 9, 5)

    def test_query_string(self):
        self._run(23, 12, 4, 8, query_string={"a": "1", "b": "2"})

    def test_post_form(self):
        self._run(37, 3, 15, 2, method="POST", data={"k": "v", "q": "w"})

    def test_json_body(self):
        self._run(41, 18, 6, 11, method="PUT", json={"x": [1, 2, 3]})

    def test_no_pkg_resources(self):
        self._run(53, 9, 13, 6, use_pkg=False)

    def test_https_base_url(self):
        self._run(67, 5, 10, 14, base_url="https://example.org/app/")

    def test_raw_text_body(self):
        self._run(71, 14, 3, 0, method="PATCH", data="hello world",
                  content_type="text/plain")

    def test_many_headers(self):
        self._run(83, 0, 7, 21)

    def test_empty_everything(self):
        self._run(97, 0, 0, 0)

    def test_path_heavy(self):
        self._run(101, 4, 22, 3, path="/deep/nested/path")

    def test_dist_heavy(self):
        self._run(113, 25, 2, 9, method="DELETE")

    def test_extra_environ(self):
        self._run(127, 6, 8, 4,
                  environ_overrides={"custom.one": 1, "custom.two": "two"})


if __name__ == "__main__":
    unittest.main()
