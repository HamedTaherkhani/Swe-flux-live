import random
import unittest

from werkzeug.http import parse_options_header


def _build_header(rng, n_parts):
    """Build a Content-Disposition-like header with a seeded mix of parameter kinds."""
    alphabet = "abcdefghijklmnop"
    keys = ["".join(rng.choice(alphabet) for _ in range(3)) for _ in range(4)]
    pieces = ["form-data"]
    for i in range(n_parts):
        key = keys[rng.randrange(len(keys))]
        kind = rng.randrange(7)
        word = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3)))
        if kind == 0:
            pieces.append(f"{key}={word}")
        elif kind == 1:
            pieces.append(f'{key}="{word[:1]}\\"{word[1:]}"')
        elif kind == 2:
            enc = ["utf-8", "ascii", "koi8-r", ""][rng.randrange(4)]
            pieces.append(f"{key}*={enc}''{word}%41")
        elif kind == 3:
            pieces.append(f"{key}*{i % 3}={word}")
        elif kind == 4:
            enc = ["utf-8", ""][i % 2]
            pieces.append(f"{key}*{i % 2}*={enc}''{word}")
        elif kind == 5:
            pieces.append(f"{key}")
        else:
            pieces.append(f'{key}="{word}%22"')
    sep = [";", "; ", ";\t"]
    out = pieces[0]
    for j, p in enumerate(pieces[1:]):
        out += sep[j % len(sep)] + p
    return out


class ParseOptionsHeaderMixTest(unittest.TestCase):
    def test_mixed_headers(self):
        rng = random.Random(20240917)
        headers = [_build_header(rng, n) for n in (3, 5, 9, 4, 6)]
        headers.insert(1, None)
        headers.insert(3, "  text/plain  ")
        results = [parse_options_header(h) for h in headers]

        self.assertEqual(len(results), 7)
        self.assertEqual(results[1], ("", {}))
        self.assertEqual(results[3][1], {})
        for h, (value, options) in zip(headers, results):
            self.assertIsInstance(options, dict)
            if h is not None and ";" in h:
                self.assertEqual(value, "form-data")
                self.assertTrue(all(k == k.lower() for k in options))
