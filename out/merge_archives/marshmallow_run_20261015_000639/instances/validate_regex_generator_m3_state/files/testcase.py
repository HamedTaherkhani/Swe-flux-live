"""Drive URL.RegexMemoizer._regex_generator directly with patched letter classes."""

import random
import unittest
from unittest import mock

import marshmallow.validate as validate_mod
from marshmallow.validate import URL

POOL = "_~@#&!%=;:"


def make_letters(seed, size):
    rng = random.Random(seed)
    return "".join(rng.choice(POOL) for _ in range(size))


def flag_triples(seed, count):
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        rel = rng.random() < 0.5
        absolute = (not rel) or rng.random() < 0.6
        out.append((rel, absolute, rng.random() < 0.5))
    return out


class RegexGeneratorStateTest(unittest.TestCase):
    def generate(self, letters, relative, absolute, require_tld):
        with mock.patch.object(validate_mod, "_UNICODE_LETTERS", letters):
            memo = URL.RegexMemoizer()
            return memo._regex_generator(
                relative=relative, absolute=absolute, require_tld=require_tld
            )

    def test_default_letters_absolute_only(self):
        pattern = self.generate(validate_mod._UNICODE_LETTERS, False, True, True)
        self.assertIsNotNone(pattern.search("http://example.org/path"))
        self.assertIsNone(pattern.search("/just/a/path"))

    def test_empty_letters_dotless_host(self):
        pattern = self.generate("", False, True, False)
        self.assertIsNotNone(pattern.search("http://intranet/"))

    def test_seeded_letters_relative_only(self):
        letters = make_letters(3, 2)
        pattern = self.generate(letters, True, False, True)
        self.assertIsNotNone(pattern.search("/a/b?c=d"))
        self.assertIsNone(pattern.search("http://example.org"))

    def test_seeded_letters_flag_sweep(self):
        letters = make_letters(11, 3)
        sizes = set()
        for rel, absolute, tld in flag_triples(5, 6):
            sizes.add(len(self.generate(letters, rel, absolute, tld).pattern))
        self.assertGreaterEqual(len(sizes), 2)

    def test_growing_letters_prefixes(self):
        base = make_letters(21, 4)
        lengths = []
        for cut in range(1, len(base) + 1, 2):
            lengths.append(len(self.generate(base[:cut], False, True, cut % 4 == 1).pattern))
        self.assertEqual(len(lengths), 2)

    def test_reversed_letters_mixed_flags(self):
        letters = make_letters(11, 3)[::-1]
        a = self.generate(letters, True, True, False)
        b = self.generate(letters, True, True, True)
        self.assertGreater(len(a.pattern), len(b.pattern))
        self.assertIsNotNone(a.search("/relative/only"))

    def test_dedup_sorted_letters(self):
        raw = make_letters(8, 7)
        letters = "".join(sorted(set(raw)))
        pattern = self.generate(letters, False, True, True)
        self.assertTrue(pattern.pattern.startswith("^"))

    def test_letters_from_flag_counts(self):
        triples = flag_triples(9, 8)
        n_true = sum(1 for t in triples if t[2])
        letters = POOL[n_true : n_true + 2]
        for rel, absolute, tld in triples[:3]:
            pattern = self.generate(letters, rel, absolute, tld)
            if rel:
                self.assertIsNotNone(pattern.search("/x"))

    def test_repeat_same_letters_all_absolute(self):
        letters = make_letters(3, 2)
        flags = [bool(i % 2) for i in range(4)]
        compiled = [self.generate(letters, False, True, f) for f in flags]
        self.assertEqual(len({c.pattern for c in compiled}), 2)

    def test_interleaved_two_letter_sets(self):
        first = make_letters(30, 1)
        second = first + make_letters(31, 1)
        for i in range(5):
            letters = first if i % 2 == 0 else second
            self.generate(letters, i % 3 == 0, True, i >= 3)

    def test_relative_ignores_hostnames(self):
        letters = make_letters(44, 5)
        a = self.generate(letters, True, False, False)
        b = self.generate("", True, False, True)
        self.assertEqual(a.pattern, b.pattern)

    def test_ipv4_and_localhost_still_match(self):
        letters = make_letters(52, 2)
        pattern = self.generate(letters, True, True, True)
        self.assertIsNotNone(pattern.search("http://127.0.0.1:8080/x"))
        self.assertIsNotNone(pattern.search("ftp://localhost/"))
