import random
import unittest

from werkzeug.datastructures import Headers


def _casing(rng, name):
    style = rng.randrange(3)
    if style == 0:
        return name.lower()
    if style == 1:
        return name.upper()
    return "-".join(p.capitalize() for p in name.split("-"))


class TestHeadersUpdateCalls(unittest.TestCase):
    def test_update_sequence(self):
        rng = random.Random(4821)
        names = [f"X-{a}-{b}" for a in ("Alpha", "Beta", "Gamma") for b in ("One", "Two")]

        # Starting headers built from random pairs.
        target = Headers()
        for i in range(18):
            name = _casing(rng, rng.choice(names))
            target.add(name, f"v{i}-{rng.randint(0, 999)}")

        # Invocation 1: plain iterable of pairs.
        pairs = [(_casing(rng, rng.choice(names)), rng.randint(1, 50)) for _ in range(9)]
        target.update(pairs)

        # Invocation 2: another Headers object (possibly repeated keys) plus kwargs.
        source = Headers()
        for i in range(14):
            name = _casing(rng, rng.choice(names[: 3 + i % 4]))
            source.add(name, f"s{i * 7 % 23}")

        kwargs = {}
        for j in range(10):
            kind = (j * 5 + rng.randrange(4)) % 4
            if kind == 0:
                value = [rng.randint(0, 9) for _ in range(rng.randrange(0, 4))]
            elif kind == 1:
                value = tuple(f"t{j}{k}" for k in range(rng.randrange(0, 3)))
            elif kind == 2:
                value = rng.randint(100, 999)
            else:
                value = {rng.randint(0, 5) for _ in range(rng.randrange(1, 4))}
            kwargs[f"K_{j}"] = value
        target.update(source, **kwargs)

        # Invocation 3: a plain dict.
        mapping = {n: [i] * (i % 3) for i, n in enumerate(names)}
        target.update(mapping)

        self.assertIsInstance(target, Headers)
        self.assertGreater(len(target), 5)
        for n in names:
            self.assertEqual(target.getlist(n), [str(v) for v in mapping[n]])
