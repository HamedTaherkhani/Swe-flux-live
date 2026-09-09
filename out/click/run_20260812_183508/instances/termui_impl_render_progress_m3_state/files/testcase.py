import io
import os
import random
import unittest
from unittest import mock

import click


class TTYBuffer(io.StringIO):
    def isatty(self):
        return True


class Tick:
    def __init__(self, start, increments):
        self.value = start
        self.increments = tuple(increments)
        self.index = 0

    def __call__(self):
        increment = self.increments[self.index % len(self.increments)]
        self.index += 1
        self.value += increment
        return self.value


class TerminalSizes:
    def __init__(self, columns):
        self.columns = tuple(columns)
        self.index = 0

    def __call__(self):
        columns = self.columns[self.index % len(self.columns)]
        self.index += 1
        return os.terminal_size((columns, 24))


class TestRenderProgressState(unittest.TestCase):
    def run_iterable(self, values, expected_size=None, **options):
        stream = options.pop("file", TTYBuffer())
        if expected_size is None:
            expected_size = len(values)
        clock = Tick(700.0 + expected_size, (0.31, 0.83, 1.27, 0.49))
        seen = []
        with mock.patch("click._termui_impl.time.time", clock):
            with click.progressbar(values, file=stream, **options) as progress:
                for value in progress:
                    seen.append((value * value + len(seen)) % 97)
        self.assertEqual(len(seen), expected_size)
        self.assertGreaterEqual(stream.tell(), 0)
        return stream, seen

    def test_fixed_width_positions(self):
        values = [(index * index + 3 * index) % 41 for index in range(19)]
        stream, seen = self.run_iterable(
            values, label="orbit", width=11, show_pos=True, show_percent=False
        )
        self.assertTrue(stream.getvalue().endswith("\n"))
        self.assertGreater(len(set(seen)), len(values) // 2)

    def test_seeded_percentages(self):
        rng = random.Random(91827)
        values = [rng.randrange(5, 200) for _ in range(23)]
        stream, _ = self.run_iterable(
            values,
            label="quartz",
            width=17,
            fill_char="=",
            empty_char=".",
            show_percent=True,
        )
        self.assertGreater(stream.getvalue().count("\r"), len(values))

    def test_unknown_length_generator(self):
        values = [(index * 13 + index // 3) % 89 for index in range(17)]
        source = (value for value in values)
        stream, seen = self.run_iterable(
            source,
            expected_size=len(values),
            label="drift",
            width=13,
            show_pos=True,
            show_percent=False,
        )
        self.assertEqual(len(seen), len(values))
        self.assertIn("\n", stream.getvalue())

    def test_manual_variable_updates(self):
        rng = random.Random(4409)
        increments = [rng.randrange(1, 5) for _ in range(20)]
        total = sum(increments) + 7
        stream = TTYBuffer()
        clock = Tick(1300.0, (1.11, 0.24, 0.92))
        with mock.patch("click._termui_impl.time.time", clock):
            with click.progressbar(
                length=total,
                file=stream,
                label="manual",
                width=15,
                show_pos=True,
            ) as progress:
                for index, increment in enumerate(increments):
                    progress.update(increment, current_item=index * increment)
        self.assertGreater(stream.tell(), len(increments))

    def test_batched_updates(self):
        values = [(index * 7 + 4) % 53 for index in range(31)]
        stream, seen = self.run_iterable(
            values,
            label="batch",
            width=9,
            update_min_steps=4,
            show_pos=True,
            show_percent=True,
        )
        self.assertGreater(len(seen), stream.getvalue().count("\r"))

    def test_generated_item_labels(self):
        values = [(index**3 + 17) % 101 for index in range(18)]

        def describe(item):
            if item is None:
                return None
            marker = (item * 5 + 9) % 37
            return f"m{marker:x}" if marker % 3 else None

        stream, _ = self.run_iterable(
            values,
            label="items",
            width=12,
            show_pos=True,
            item_show_func=describe,
        )
        self.assertGreater(stream.getvalue().count("m"), 2)

    def test_hidden_progress(self):
        values = [(index * 29) % 67 for index in range(16)]
        stream, seen = self.run_iterable(
            values, label="veiled", width=14, hidden=True, show_pos=True
        )
        self.assertEqual(stream.getvalue(), "")
        self.assertEqual(len(seen), len(values))

    def test_non_tty_progress(self):
        values = [(index * 11 + 6) % 73 for index in range(20)]
        stream, seen = self.run_iterable(
            values,
            file=io.StringIO(),
            label="redirected",
            width=10,
            show_percent=True,
        )
        self.assertEqual(len(seen), len(values))
        self.assertGreater(stream.tell(), 0)

    def test_autowidth_rotating_terminal(self):
        values = [(index * index * 5 + 2) % 113 for index in range(22)]
        sizes = TerminalSizes(72 + ((index * 17) % 19) for index in range(61))
        with mock.patch("shutil.get_terminal_size", sizes):
            stream, _ = self.run_iterable(
                values, label="resize", width=0, show_pos=True, show_percent=True
            )
        self.assertGreater(stream.getvalue().count("\r"), len(values))

    def test_autowidth_shrinking_terminal(self):
        values = [(index * 31 + index**2) % 127 for index in range(18)]
        columns = [96 - ((index * 7) % 43) for index in range(79)]
        with mock.patch("shutil.get_terminal_size", TerminalSizes(columns)):
            stream, _ = self.run_iterable(
                values,
                label="contract",
                width=0,
                fill_char="+",
                empty_char="_",
                show_pos=True,
            )
        self.assertGreater(stream.tell(), len(values) * 2)

    def test_empty_iterable_edge(self):
        stream, seen = self.run_iterable(
            [], label="vacant", width=8, show_pos=True, show_percent=True
        )
        self.assertFalse(seen)
        self.assertTrue(stream.getvalue().endswith("\n"))

    def test_unicode_custom_template(self):
        values = [(index * 19 + 8) % 79 for index in range(21)]
        stream, seen = self.run_iterable(
            values,
            label="phase-λ",
            width=16,
            bar_template="%(label)s ‹%(bar)s› %(info)s",
            info_sep=" | ",
            fill_char="◆",
            empty_char="·",
            show_eta=False,
            show_pos=True,
        )
        self.assertEqual(len(seen), len(values))
        self.assertIn("λ", stream.getvalue())
