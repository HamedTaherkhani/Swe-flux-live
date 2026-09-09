from __future__ import annotations

import random
import string
import unittest
from http.cookiejar import Cookie

from scrapy.http import Request
from scrapy.http.cookies import CookieJar


class CookieHeaderInvariantTest(unittest.TestCase):
    @staticmethod
    def _hostname(seed: int, label_count: int) -> str:
        rng = random.Random(seed)
        labels = [
            "".join(rng.choice(string.ascii_lowercase) for _ in range(4 + index % 5))
            for index in range(label_count)
        ]
        return ".".join(labels)

    @staticmethod
    def _cookie(domain: str, index: int, host_only: bool) -> Cookie:
        return Cookie(
            version=0,
            name=f"k{index:x}",
            value=f"v{(index * index + len(domain)) % 997:x}",
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=not host_only,
            domain_initial_dot=domain.startswith("."),
            path="/" if index % 3 else "/vault",
            path_specified=True,
            secure=index % 7 == 0,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )

    def _exercise(
        self,
        *,
        seed: int,
        label_count: int,
        cookie_count: int,
        preset_header: bool = False,
        single_label: bool = False,
        ipv4: bool = False,
        frequency: int = 10000,
    ) -> None:
        rng = random.Random(seed ^ 0x5A17)
        if ipv4:
            octets = [11 + rng.randrange(211) for _ in range(4)]
            host = ".".join(str(value) for value in octets)
        elif single_label:
            host = self._hostname(seed, 1)
        else:
            host = self._hostname(seed, label_count)

        scheme = "https" if seed % 3 == 0 else "http"
        headers = {"Cookie": f"prior={rng.getrandbits(40):x}"} if preset_header else {}
        request = Request(f"{scheme}://{host}/section/{seed % 11}", headers=headers)
        jar = CookieJar(check_expired_frequency=frequency)

        labels = host.split(".")
        domains = [host]
        if not ipv4 and len(labels) > 1:
            domains.extend(
                "." + ".".join(labels[offset:])
                for offset in range(1, len(labels) - 1)
            )
        if single_label:
            domains.append(host + ".local")

        for index in range(cookie_count):
            domain = domains[(index * 7 + rng.randrange(len(domains))) % len(domains)]
            host_only = domain == host and index % 4 == 1
            jar.set_cookie(self._cookie(domain, index + seed % 13, host_only))

        before = tuple(request.headers.getlist("Cookie"))
        jar.add_cookie_header(request)
        after = tuple(request.headers.getlist("Cookie"))

        self.assertGreater(jar.processed, 0)
        self.assertIsInstance(after, tuple)
        if preset_header:
            self.assertEqual(before, after)

    def test_deep_domain_cookie_mix(self):
        self._exercise(seed=91207, label_count=15, cookie_count=73, frequency=1)

    def test_sparse_suffix_domains(self):
        self._exercise(seed=44819, label_count=14, cookie_count=36, frequency=2)

    def test_secure_request_dense_jar(self):
        self._exercise(seed=60309, label_count=13, cookie_count=65, frequency=3)

    def test_existing_header_blocks_append(self):
        self._exercise(
            seed=51876, label_count=12, cookie_count=48, preset_header=True, frequency=1
        )

    def test_ipv4_host_candidates(self):
        self._exercise(seed=69741, label_count=3, cookie_count=47, ipv4=True, frequency=2)

    def test_single_label_local_candidates(self):
        self._exercise(
            seed=77228, label_count=1, cookie_count=39, single_label=True, frequency=1
        )

    def test_empty_jar_long_hostname(self):
        self._exercise(seed=85317, label_count=15, cookie_count=0, frequency=1)

    def test_frequent_expiry_sweep(self):
        self._exercise(
            seed=21547, label_count=15, cookie_count=65, frequency=1
        )

    def test_two_label_boundary(self):
        self._exercise(seed=38763, label_count=2, cookie_count=45, frequency=5)

    def test_odd_label_lengths(self):
        self._exercise(seed=61382, label_count=14, cookie_count=55, frequency=2)

    def test_shallow_domain_many_cookies(self):
        self._exercise(seed=92956, label_count=9, cookie_count=55, frequency=1)

    def test_preset_header_with_expiry(self):
        self._exercise(
            seed=34689,
            label_count=15,
            cookie_count=65,
            preset_header=True,
            frequency=1,
        )