import random
import unittest

from werkzeug.urls import iri_to_uri

ASCII_LABELS = ["alpha", "Beta", "gamma", "delta", "exa-mple", "node7", "www", "cdn"]
UNI_LABELS = ["münchen", "café", "☃", "españa", "köln", "åland"]
TLDS = ["com", "net", "org", "de", "io"]
PATH_SEGS = ["påth", "docs", "a b", "%7Euser", "über", "x;y=1", "日本", "ok"]
QUERY_KEYS = ["q", "lang", "søk", "page", "x y"]
QUERY_VALS = ["èry", "1", "%DF", "a/b", "☃", "", "v?w"]
USERS = ["bob", "jørn", "a b", "", "ad%40min", "émile"]
PASSWORDS = ["secret", "", "p@ss", "üml", "x:y"]


def _host(rng, uni_ratio):
    labels = []
    for _ in range(rng.randint(1, 3)):
        pool = UNI_LABELS if rng.random() < uni_ratio else ASCII_LABELS
        labels.append(rng.choice(pool))
    return ".".join(labels + [rng.choice(TLDS)])


def _ipv6(rng):
    groups = [format(rng.randrange(0, 0x10000), "x") for _ in range(rng.choice([2, 3, 4]))]
    return "[" + groups[0] + "::" + ":".join(groups[1:]) + "]"


def _path(rng):
    return "/" + "/".join(rng.choice(PATH_SEGS) for _ in range(rng.randint(0, 3)))


def _query(rng):
    n = rng.randint(0, 3)
    return "&".join(f"{rng.choice(QUERY_KEYS)}={rng.choice(QUERY_VALS)}" for _ in range(n))


def _userinfo(rng, p_user, p_pass):
    if rng.random() >= p_user:
        return ""
    user = rng.choice(USERS)
    if rng.random() < p_pass:
        return f"{user}:{rng.choice(PASSWORDS)}@"
    return f"{user}@"


def _assemble(scheme, info, host, port, path, query, frag):
    url = f"{scheme}://{info}{host}"
    if port is not None:
        url += f":{port}"
    url += path
    if query:
        url += "?" + query
    if frag:
        url += "#" + frag
    return url


class IriToUriFlowTest(unittest.TestCase):
    def _check(self, iris):
        out = [iri_to_uri(i) for i in iris]
        for src, res in zip(iris, out):
            self.assertTrue(res.isascii(), res)
            self.assertEqual(src.count("#") > 0, "#" in res)
        return out

    def test_plain_ascii_hosts(self):
        rng = random.Random(101)
        iris = [
            _assemble("http", "", _host(rng, 0.0), None, _path(rng), _query(rng), "")
            for _ in range(12)
        ]
        self._check(iris)

    def test_unicode_hosts_with_ports(self):
        rng = random.Random(202)
        iris = []
        for i in range(14):
            port = rng.choice([None, 80, 8443, 0, 3000]) if i % 3 else None
            iris.append(_assemble("https", "", _host(rng, 0.7), port, _path(rng), "", ""))
        self._check(iris)

    def test_ipv6_literals(self):
        rng = random.Random(303)
        iris = []
        for i in range(10):
            port = rng.randrange(1, 65535) if rng.random() < 0.5 else None
            iris.append(_assemble("http", "", _ipv6(rng), port, _path(rng), _query(rng), ""))
        self._check(iris)

    def test_userinfo_without_password(self):
        rng = random.Random(404)
        iris = [
            _assemble("ftp", _userinfo(rng, 1.0, 0.0), _host(rng, 0.4), None, _path(rng), "", "")
            for _ in range(11)
        ]
        self._check(iris)

    def test_userinfo_mixed_passwords(self):
        rng = random.Random(505)
        iris = []
        for _ in range(16):
            port = rng.choice([None, None, 21, 2121])
            iris.append(
                _assemble("ftp", _userinfo(rng, 0.8, 0.5), _host(rng, 0.5), port, _path(rng), "", "")
            )
        self._check(iris)

    def test_hostless_urls(self):
        rng = random.Random(606)
        iris = []
        for _ in range(9):
            kind = rng.randrange(3)
            if kind == 0:
                iris.append("/" + "/".join(rng.choice(PATH_SEGS) for _ in range(rng.randint(1, 3))))
            elif kind == 1:
                iris.append("file:///" + rng.choice(PATH_SEGS) + "?" + _query(rng))
            else:
                iris.append("mailto:" + rng.choice(USERS) + "@" + _host(rng, 0.5))
        self._check(iris)

    def test_empty_host_with_port_or_user(self):
        rng = random.Random(707)
        iris = []
        for _ in range(8):
            info = _userinfo(rng, 0.6, 0.5)
            port = rng.choice([None, 0, 8080])
            iris.append(_assemble("http", info, "", port, _path(rng), _query(rng), ""))
        self._check(iris)

    def test_fragments_and_queries(self):
        rng = random.Random(808)
        iris = []
        for _ in range(13):
            frag = rng.choice(["", "secção", "top", "a#b", "☃!"])
            iris.append(_assemble("https", "", _host(rng, 0.3), None, _path(rng), _query(rng), frag))
        self._check(iris)

    def test_ipv6_with_credentials(self):
        rng = random.Random(909)
        iris = []
        for _ in range(7):
            port = rng.choice([None, 443, 0])
            iris.append(_assemble("https", _userinfo(rng, 0.9, 0.6), _ipv6(rng), port, _path(rng), "", ""))
        self._check(iris)

    def test_derived_chain(self):
        rng = random.Random(1010)
        iris = []
        prev = _host(rng, 0.5)
        for i in range(12):
            host = prev if i % 4 == 3 else _host(rng, 0.5)
            info = _userinfo(rng, 0.5, 0.5) if i % 2 else ""
            port = (len(host) * 97) % 9000 if len(host) % 3 == 0 else None
            iris.append(_assemble("http", info, host, port, _path(rng), _query(rng), ""))
            prev = host
        self._check(iris)

    def test_ipv4_hosts(self):
        rng = random.Random(1111)
        iris = []
        for _ in range(10):
            ip = ".".join(str(rng.randrange(0, 256)) for _ in range(4))
            port = rng.choice([None, 22, 8000])
            iris.append(_assemble("ssh", _userinfo(rng, 0.5, 0.3), ip, port, "", "", ""))
        self._check(iris)

    def test_mixed_everything(self):
        rng = random.Random(1212)
        iris = []
        for _ in range(20):
            kind = rng.randrange(4)
            if kind == 0:
                host = _ipv6(rng)
            elif kind == 3:
                host = ""
            else:
                host = _host(rng, 0.5)
            port = rng.choice([None, None, 0, 9090])
            if host == "" and port is None and rng.random() < 0.5:
                port = 1
            frag = rng.choice(["", "", "fråg"])
            iris.append(
                _assemble(rng.choice(["http", "https"]), _userinfo(rng, 0.5, 0.5), host, port, _path(rng), _query(rng), frag)
            )
        self._check(iris)
