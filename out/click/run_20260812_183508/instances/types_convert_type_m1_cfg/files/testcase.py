import builtins
from types import SimpleNamespace
import unittest
from unittest import mock

import click
import click.types as click_types


class TestIndirectChoiceMetavars(unittest.TestCase):
    @staticmethod
    def _guessed_type(candidate, default):
        route = getattr(candidate, "_qa_route", None)
        if route is None:
            return candidate
        if route == 0:
            return (str, int)
        if route == 1:
            return click.STRING
        if route == 2:
            return str
        if route == 3:
            return None
        if route == 4:
            return int
        if route == 5:
            return float
        if route == 6:
            return bool
        if route == 7:
            return bytes
        return candidate

    @staticmethod
    def _checked_subclass(candidate, parent):
        if getattr(candidate, "_qa_force_type_error", False):
            raise TypeError("synthetic non-class probe")
        return builtins.issubclass(candidate, parent)

    def _choice_value(self, seed, index, route):
        attributes = {"_qa_route": route}
        if route == 9:
            attributes["_qa_force_type_error"] = True
        generated = builtins.type(
            f"Generated_{seed:x}_{index:x}_{route:x}", (), attributes
        )
        return generated()

    def _exercise(self, seed, size, step):
        values = [
            self._choice_value(seed, index, (seed + index * step) % 10)
            for index in range(size)
        ]
        choice = click_types.Choice(values)
        parameter = SimpleNamespace(
            param_type_name="option", show_choices=False, required=False
        )

        with (
            mock.patch.object(
                click_types, "_guess_type", side_effect=self._guessed_type
            ),
            mock.patch.object(
                click_types,
                "issubclass",
                side_effect=self._checked_subclass,
                create=True,
            ),
        ):
            metavar = choice.get_metavar(parameter, None)

        self.assertTrue(metavar.startswith("["))
        self.assertTrue(metavar.endswith("]"))
        self.assertTrue(any(character.isalpha() for character in metavar))

    def _exercise_assertion(self, seed, prefix_size, step):
        values = [
            self._choice_value(seed, index, (seed + index * step) % 10)
            for index in range(prefix_size)
        ]
        invalid_type = builtins.type(
            f"Uninstantiated_{seed:x}",
            (click_types.ParamType,),
            {"_qa_route": 10},
        )
        values.append(invalid_type())
        choice = click_types.Choice(values)
        parameter = SimpleNamespace(
            param_type_name="option", show_choices=False, required=False
        )

        with (
            mock.patch.object(
                click_types, "_guess_type", side_effect=self._guessed_type
            ),
            mock.patch.object(
                click_types,
                "issubclass",
                side_effect=self._checked_subclass,
                create=True,
            ),
            self.assertRaises(AssertionError),
        ):
            choice.get_metavar(parameter, None)

    def test_alpha_rotating_routes(self):
        self._exercise(137, 23, 3)

    def test_bravo_long_reverse_cycle(self):
        self._exercise(211, 31, 9)

    def test_charlie_offset_cycle(self):
        self._exercise(293, 27, 7)

    def test_delta_dense_cycle(self):
        self._exercise(359, 34, 3)

    def test_echo_shifted_reverse(self):
        self._exercise(431, 29, 9)

    def test_foxtrot_wide_cycle(self):
        self._exercise(503, 38, 7)

    def test_golf_uneven_cycle(self):
        self._exercise(577, 26, 3)

    def test_hotel_extended_reverse(self):
        self._exercise(647, 41, 9)

    def test_india_shifted_cycle(self):
        self._exercise(719, 33, 7)

    def test_juliet_compact_cycle(self):
        self._exercise(787, 22, 3)

    def test_kilo_late_uninstantiated_type(self):
        self._exercise_assertion(863, 24, 9)

    def test_lima_deeper_uninstantiated_type(self):
        self._exercise_assertion(941, 36, 7)
