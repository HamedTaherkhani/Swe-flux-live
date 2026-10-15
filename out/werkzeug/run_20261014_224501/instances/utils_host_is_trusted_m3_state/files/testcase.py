import random
import unittest

from werkzeug.sansio.utils import host_is_trusted

LATIN = "abcdefghijklmnopqrstuvwxyz"
ACCENTED = "äöüßéèñçøå"
TLDS = ["de", "org", "net", "io", "com"]


def make_label(rng, length, accent_ratio):
    chars = []
    for _ in range(length):
        if rng.random() < accent_ratio:
            chars.append(rng.choice(ACCENTED))
        else:
            chars.append(rng.choice(LATIN))
    return "".join(chars)


def make_domain(rng, accent_ratio=0.3):
    label = make_label(rng, rng.randint(3, 7), accent_ratio)
    return f"{label}.{rng.choice(TLDS)}"


def to_ascii(name):
    return name.lstrip(".").encode("idna").decode("ascii")


class HostIsTrustedStateTest(unittest.TestCase):
    def test_suffix_scan_until_last(self):
        rng = random.Random(11)
        refs = [("." if i % 2 else "") + make_domain(rng) for i in range(6)]
        host = "api." + to_ascii(refs[-1]) + ":8443"
        self.assertTrue(host_is_trusted(host, refs))

    def test_exact_match_midway(self):
        rng = random.Random(23)
        refs = [make_domain(rng, 0.5) for _ in range(7)]
        target = to_ascii(refs[3])
        self.assertTrue(host_is_trusted(target, refs))

    def test_no_match_full_scan(self):
        rng = random.Random(37)
        refs = ["." + make_domain(rng, 0.2) for _ in range(5)]
        self.assertFalse(host_is_trusted("unrelated.example:80", refs))

    def test_plain_string_trusted_list(self):
        rng = random.Random(41)
        ref = "." + make_domain(rng, 0.6)
        sub = make_label(rng, 4, 0.0)
        self.assertTrue(host_is_trusted(f"{sub}.{to_ascii(ref)}", ref))

    def test_invalid_host_characters(self):
        rng = random.Random(53)
        refs = [make_domain(rng) for _ in range(3)]
        bad = "host_" + make_label(rng, 5, 0.0) + ".com"
        self.assertFalse(host_is_trusted(bad, refs))
        self.assertFalse(host_is_trusted(None, refs))

    def test_port_out_of_range(self):
        rng = random.Random(59)
        refs = [make_domain(rng) for _ in range(3)]
        port = sum(ord(c) for c in refs[0]) * 97
        host = to_ascii(refs[0]) + f":{port}"
        self.assertEqual(host_is_trusted(host, refs), port <= 65535)

    def test_empty_trusted_list(self):
        self.assertTrue(host_is_trusted("example.com:443", []))
        self.assertTrue(host_is_trusted("example.com", None))

    def test_idna_failure_propagates(self):
        rng = random.Random(67)
        refs = [make_domain(rng, 0.4) for _ in range(3)]
        refs.append("." + make_label(rng, 3, 0.5) + "..bad")
        refs.append(make_domain(rng))
        with self.assertRaises(UnicodeError):
            host_is_trusted("nowhere.test", refs)

    def test_zero_width_joiner_removed(self):
        rng = random.Random(71)
        base = [make_label(rng, 4, 0.0) for _ in range(4)]
        refs = ["." + b[:2] + "‍" + b[2:] + ".net" for b in base]
        host = "www." + base[2] + ".net"
        self.assertTrue(host_is_trusted(host, refs))

    def test_uppercase_refs(self):
        rng = random.Random(83)
        refs = [make_domain(rng, 0.5).upper() for _ in range(4)]
        refs = [r if i % 2 else "." + r for i, r in enumerate(refs)]
        host = "m." + to_ascii(refs[2]).lower()
        result = host_is_trusted(host, refs)
        self.assertIsInstance(result, bool)

    def test_ipv6_hosts(self):
        refs = [f"[{i:x}::{i * 7:x}]" for i in range(9, 13)]
        self.assertTrue(host_is_trusted(refs[2] + ":8080", refs))
        self.assertFalse(host_is_trusted("[::1]", refs))

    def test_many_hosts_against_shared_list(self):
        rng = random.Random(97)
        refs = [("." if rng.random() < 0.5 else "") + make_domain(rng, 0.35) for _ in range(5)]
        hosts = []
        for r in refs:
            plain = to_ascii(r)
            hosts.append(plain if not r.startswith(".") else "x." + plain)
        hosts.append("deep.sub." + to_ascii(refs[1]))
        results = [host_is_trusted(h, refs) for h in hosts]
        self.assertEqual(len(results), len(hosts))
        self.assertTrue(results[0])
