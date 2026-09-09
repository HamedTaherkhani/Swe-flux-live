import unittest

import click


class TestShortOptionParsingMatrix(unittest.TestCase):
    @staticmethod
    def _letters(size, offset=0):
        base = ord("a") + offset
        return [chr(base + index) for index in range(size)]

    @staticmethod
    def _flag_options(chars, prefix="-"):
        return [click.Option([f"{prefix}{char}"], is_flag=True) for char in chars]

    def _parse(self, params, args, **context_settings):
        command = click.Command(
            "matrix-probe", params=params, add_help_option=False
        )
        with command.make_context(
            "matrix-probe", list(args), **context_settings
        ) as context:
            return dict(context.params), list(context.args)

    def test_dense_rotating_flag_clusters(self):
        chars = self._letters(8)
        params = self._flag_options(chars)
        args = [
            "-" + "".join(chars[shift:] + chars[:shift])
            for shift in range(5)
        ]
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertEqual(set(values), set(chars))
        self.assertTrue(all(values.values()))

    def test_count_options_accumulate_across_rotations(self):
        chars = self._letters(6, 2)
        params = [click.Option([f"-{char}"], count=True) for char in chars]
        args = [
            "-" + "".join(chars[(index * 2) % len(chars) :] + chars[: (index * 2) % len(chars)])
            for index in range(7)
        ]
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertEqual(sum(values.values()), sum(len(item) - 1 for item in args))

    def test_attached_values_terminate_clusters(self):
        flags = self._letters(4)
        params = self._flag_options(flags)
        params.append(click.Option(["-v"]))
        args = [
            "-" + "".join(flags[index:] + flags[:index]) + "v" + f"payload-{index * index:x}"
            for index in range(4)
        ]
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertTrue(values["v"].startswith("payload-"))
        self.assertTrue(all(values[char] for char in flags))

    def test_separate_values_are_consumed_from_remaining_args(self):
        flags = self._letters(3, 4)
        params = self._flag_options(flags)
        params.append(click.Option(["-q"]))
        args = []
        for index in range(5):
            args.extend(
                [
                    "-" + "".join(flags[index % len(flags) :] + flags[: index % len(flags)]) + "q",
                    f"value-{index + len(flags)}",
                ]
            )
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertIn("-", values["q"])

    def test_multi_value_option_consumes_tuple_slices(self):
        flags = self._letters(3, 7)
        params = self._flag_options(flags)
        params.append(click.Option(["-m"], nargs=3))
        args = []
        for index in range(3):
            args.append("-" + "".join(flags[::-1]) + "m")
            args.extend(f"part-{index}-{part}" for part in range(3))
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertEqual(len(values["m"]), len(flags))
        self.assertTrue(all(values[char] for char in flags))

    def test_ignored_unknowns_are_recombined(self):
        known = self._letters(5)
        params = self._flag_options(known)
        unknown = self._letters(3, 20)
        args = [
            "-" + "".join(
                known[(index + 1) % len(known) :] + unknown[: index % len(unknown) + 1]
            )
            for index in range(6)
        ]
        values, leftovers = self._parse(
            params,
            args,
            ignore_unknown_options=True,
            allow_extra_args=True,
        )
        self.assertEqual(set(values), set(known))
        self.assertTrue(all(item.startswith("-") for item in leftovers))

    def test_case_normalization_changes_option_lookup(self):
        chars = self._letters(7, 1)
        params = self._flag_options(chars)
        args = [
            "-" + "".join(chars[shift:] + chars[:shift]).upper()
            for shift in range(4)
        ]
        values, leftovers = self._parse(
            params, args, token_normalize_func=str.lower
        )
        self.assertFalse(leftovers)
        self.assertEqual(set(values), set(chars))

    def test_alternate_prefix_clusters(self):
        chars = self._letters(6, 3)
        params = self._flag_options(chars, prefix="/")
        args = [
            "/" + "".join(chars[-shift:] + chars[:-shift])
            for shift in range(1, 6)
        ]
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertTrue(all(values.values()))

    def test_interspersed_positionals_do_not_stop_scanning(self):
        chars = self._letters(5, 5)
        params = self._flag_options(chars)
        args = []
        for index in range(6):
            args.extend(
                [
                    f"word-{index * index + 1:x}",
                    "-" + "".join(chars[index % len(chars) :] + chars[: index % len(chars)]),
                ]
            )
        values, leftovers = self._parse(
            params, args, allow_extra_args=True
        )
        self.assertEqual(len(leftovers), len(args) // 2)
        self.assertTrue(all(values.values()))

    def test_noninterspersed_mode_stops_after_positional(self):
        chars = self._letters(6, 8)
        params = self._flag_options(chars)
        leading = ["-" + "".join(chars[index:] + chars[:index]) for index in range(3)]
        trailing = ["-" + "".join(reversed(chars))]
        args = leading + ["boundary-" + "".join(chars[::2])] + trailing
        values, leftovers = self._parse(
            params,
            args,
            allow_interspersed_args=False,
            allow_extra_args=True,
        )
        self.assertEqual(leftovers[-1], trailing[0])
        self.assertTrue(all(values.values()))

    def test_unknown_option_failure_after_known_prefix(self):
        chars = self._letters(5, 10)
        params = self._flag_options(chars)
        unknown = chr(ord("z"))
        args = [
            "-" + "".join(chars[index:] + chars[:index]) + unknown
            for index in range(4)
        ]
        command = click.Command(
            "matrix-probe", params=params, add_help_option=False
        )
        with self.assertRaises(click.NoSuchOption):
            command.make_context("matrix-probe", args)

    def test_resilient_parsing_absorbs_unknown_option(self):
        chars = self._letters(7, 2)
        params = self._flag_options(chars)
        suffix = chr(ord("z"))
        args = [
            "-" + "".join(chars[index:] + chars[:index]) + suffix
            for index in range(5)
        ]
        values, leftovers = self._parse(
            params, args, resilient_parsing=True
        )
        self.assertIsInstance(values, dict)
        self.assertIsInstance(leftovers, list)

    def test_mixed_long_and_short_processing(self):
        chars = self._letters(5, 12)
        params = self._flag_options(chars)
        params.extend(
            click.Option([f"--field-{index:x}"])
            for index in range(4)
        )
        args = []
        for index in range(4):
            args.extend(
                [
                    f"--field-{index:x}=datum-{index * index + 2:x}",
                    "-" + "".join(chars[index:] + chars[:index]),
                ]
            )
        values, leftovers = self._parse(params, args)
        self.assertFalse(leftovers)
        self.assertTrue(all(values[char] for char in chars))
        self.assertEqual(
            len([name for name in values if name.startswith("field_")]),
            len(params) - len(chars),
        )
