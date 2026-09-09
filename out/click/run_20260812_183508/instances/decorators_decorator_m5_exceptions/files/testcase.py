import random
import unittest

import click


_observed_objects = []


class _DeferredCallback:
    def __init__(self, marker):
        self.marker = marker
        self.__name__ = f"deferred_{marker}_command"
        self.__doc__ = f"generated callback {marker}"

    def __call__(self):
        return self.marker

    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, name)
        except Exception as exc:
            _observed_objects.append(exc)
            raise


class _BranchingCommand(click.Command):
    def __init__(self, *args, **kwargs):
        marker = kwargs.pop("marker")
        mode = marker % (len("branching") + 3)
        params = kwargs.get("params", ())

        if mode == 1:
            marker // (len(params) - len(params))
        elif mode == 2:
            {marker: marker}[marker + 1]
        elif mode == 3:
            [marker][len(params) + 1]
        elif mode == 4:
            bytes((marker % pow(2, 7), pow(2, 8) - 1)).decode("ascii")
        elif mode == 5:
            int(chr(ord("q") + marker % 4) * (marker % 3 + 1))
        elif mode == 6:
            next(iter(range(marker % 1)))
        elif mode == 7:
            raise _observed_objects.pop()
        elif mode == 8:
            try:
                float(pow(10, len("overflowing") * 100))
            except ArithmeticError:
                pass
        elif mode == 9:
            assert marker < 0
        elif mode == 10:
            sum(marker)

        super().__init__(*args, **kwargs)


class DecoratorsDecoratorExceptionTests(unittest.TestCase):
    def _exercise(self, seed, width, offset):
        markers = list(range(offset, offset + width))
        random.Random(seed).shuffle(markers)
        completed = 0
        failed = 0

        for position, marker in enumerate(markers):
            mode = marker % (len("branching") + 3)

            if mode == 7:
                callback = _DeferredCallback(marker)
            else:
                def callback(value=marker):
                    return value

                callback.__name__ = f"task_{seed}_{position}_command"
                callback.__doc__ = f"generated task {marker}"

                if (marker * seed + position) % 4 == 0:
                    callback = click.option(
                        f"--item-{seed}-{position}", default=marker
                    )(callback)

            factory = click.group if (marker + seed) % 3 == 0 else click.command

            try:
                created = factory(cls=_BranchingCommand, marker=marker)(callback)
            except Exception:
                failed += 1
                continue

            completed += 1
            self.assertIsInstance(created, click.Command)

            if (marker + position + seed) % 5 == 0:
                try:
                    click.group(created)
                except Exception:
                    failed += 1

        self.assertLessEqual(completed, width)
        self.assertEqual(len(markers), width)
        self.assertGreater(completed, 0)
        self.assertGreater(failed, 0)
        self.assertFalse(_observed_objects)

    def test_seeded_window_alpha(self):
        self._exercise(5 * 8 + 1, 2 ** 4 + 1, 5)

    def test_seeded_window_beta(self):
        self._exercise(9 * 8 + 1, 2 ** 4 + 3, 3 ** 3 - 4)

    def test_seeded_window_gamma(self):
        self._exercise(5 ** 3 - 2 * 9, 2 ** 4 + 5, 6 * 8 - 1)

    def test_seeded_window_delta(self):
        self._exercise(7 * 7 * 3 + 2, 2 ** 4 + 7, 9 * 8 - 1)

    def test_seeded_window_epsilon(self):
        self._exercise(8 * 8 * 3 - 1, 2 ** 4 + 3 ** 2, 5 * 5 * 4 + 1)

    def test_seeded_window_zeta(self):
        self._exercise(6 ** 3 + 2 ** 4 + 1, 3 ** 3, 5 ** 3 + 6)

    def test_seeded_window_eta(self):
        self._exercise(3 ** 5 + 4 * 8 + 2, 2 ** 4 + 2, 7 * 8 * 3 - 1)

    def test_seeded_window_theta(self):
        self._exercise(5 ** 3 * 2 + 7 * 9, 2 ** 4 + 4, 5 * 8 * 5 - 3)

    def test_seeded_window_iota(self):
        self._exercise(6 ** 3 + 7 * 7 * 3 - 4, 2 ** 4 + 6, 6 ** 3 + 2 ** 4 - 3)

    def test_seeded_window_kappa(self):
        self._exercise(5 * 8 * 9 + 5 * 8 + 1, 3 * 8, 3 ** 5 + 2 * 9 + 2)

    def test_seeded_window_lambda(self):
        self._exercise(7 * 8 * 8 - 5, 3 ** 3 - 1, 5 ** 3 * 2 + 6 * 9 + 3)

    def test_seeded_window_mu(self):
        self._exercise(6 * 9 * 9 + 1, 3 ** 3 + 1, 7 * 7 * 7 + 2 * 5)
