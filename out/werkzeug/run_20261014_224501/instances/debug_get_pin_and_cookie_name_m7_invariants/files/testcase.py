import os
import random
import sys
import types
import unittest
from unittest import mock

import werkzeug.debug as wdebug
from werkzeug.debug import get_pin_and_cookie_name

ALPHA = "abcdefghijklmnopqrstuvwxyz"


def _word(rng, lo, hi):
    return "".join(rng.choice(ALPHA) for _ in range(rng.randint(lo, hi)))


def _wsgi(environ, start_response):  # pragma: no cover - never served
    return []


def make_app(kind, modname, name):
    if kind == "func":

        def app(environ, start_response):  # pragma: no cover
            return []

        app.__module__ = modname
        app.__name__ = name
        return app
    cls = type(name, (), {"__module__": modname, "__call__": staticmethod(_wsgi)})
    if kind == "cls":
        return cls
    return cls()


class TestPinAndCookieInvariants(unittest.TestCase):
    def setUp(self):
        self._added = []
        rng = random.Random(4242)
        self.modnames = []
        for i in range(8):
            name = f"qa_pin_mod_{_word(rng, 2, 9)}_{i}"
            mod = types.ModuleType(name)
            choice = i % 4
            if choice == 0:
                mod.__file__ = "/srv/" + "/".join(_word(rng, 1, 6) for _ in range(i + 1)) + ".py"
            elif choice == 1:
                mod.__file__ = ""
            elif choice == 2:
                mod.__file__ = _word(rng, 3, 5) + ".py"
            # choice 3: no __file__ attribute at all
            sys.modules[name] = mod
            self._added.append(name)
            self.modnames.append(name)

    def tearDown(self):
        for name in self._added:
            sys.modules.pop(name, None)

    def _run(self, app, pin, user="qa", node=0x1A2B3C4D5E, machine=b"qa-machine"):
        env = dict(os.environ)
        env.pop("WERKZEUG_DEBUG_PIN", None)
        if pin is not None:
            env["WERKZEUG_DEBUG_PIN"] = pin
        if isinstance(user, type) and issubclass(user, BaseException):
            user_patch = mock.patch("getpass.getuser", side_effect=user)
        else:
            user_patch = mock.patch("getpass.getuser", return_value=user)
        with mock.patch.dict(os.environ, env, clear=True), user_patch, mock.patch(
            "uuid.getnode", return_value=node
        ), mock.patch.object(wdebug, "get_machine_id", return_value=machine):
            return get_pin_and_cookie_name(app)

    def _check(self, result):
        rv, cookie = result
        self.assertTrue(cookie.startswith("__wzd"))
        self.assertEqual(len(cookie), 25)
        self.assertIsInstance(rv, str)
        return rv, cookie

    def test_generated_pins_func_apps(self):
        rng = random.Random(1)
        for i in range(9):
            app = make_app("func", self.modnames[i % 8], _word(rng, 1, 15))
            rv, _ = self._check(self._run(app, None, user=_word(rng, 2, 14)))
            self.assertEqual(rv.replace("-", "").isdigit(), True)

    def test_explicit_plain_numeric_pins(self):
        rng = random.Random(2)
        for length in range(6, 17):
            pin = "".join(str(rng.randint(0, 9)) for _ in range(length))
            app = make_app("func", self.modnames[length % 8], "app" * (length % 5 + 1))
            rv, _ = self._check(self._run(app, pin))
            self.assertEqual(rv.replace("-", ""), pin)

    def test_dashed_pins_returned_verbatim(self):
        rng = random.Random(3)
        for i in range(7):
            groups = [str(rng.randint(1, 10 ** rng.randint(1, 4))) for _ in range(i % 3 + 1)]
            pin = "-".join(groups) + ("-" if i % 4 == 3 else "")
            app = make_app("obj", self.modnames[(i * 3) % 8], "Dash" + _word(rng, 1, 10))
            rv, _ = self._check(self._run(app, pin))
            self.assertEqual(rv, pin)

    def test_off_lookalikes_do_not_disable(self):
        rng = random.Random(4)
        variants = ["Off", "OFF", " off", "off\n", "of-f", "o" + "ff" * 2]
        for i, pin in enumerate(variants):
            app = make_app("func", self.modnames[(i + 5) % 8], _word(rng, 4, 13))
            rv, cookie = self._check(self._run(app, pin, machine=_word(rng, 5, 30)))
            self.assertEqual(len(rv.split("-")), 3)

    def test_unknown_user_and_unregistered_modules(self):
        rng = random.Random(5)
        for i in range(6):
            modname = "qa_missing_" + _word(rng, 1, 8)
            app = make_app(["func", "cls", "obj"][i % 3], modname, _word(rng, 2, 16))
            exc = KeyError if i % 2 == 0 else OSError
            rv, _ = self._check(self._run(app, None, user=exc))
            self.assertTrue(rv)

    def test_unicode_digit_pins(self):
        rng = random.Random(6)
        bases = [0x0660, 0x06F0, 0x0966, 0xFF10]
        for i in range(8):
            base = bases[i % 4]
            length = rng.randint(5, 13)
            pin = "".join(chr(base + rng.randint(0, 9)) for _ in range(length))
            if i % 3 == 2:
                pin = pin[:3] + "-" + pin[3:]
            app = make_app("cls", self.modnames[i % 8], "Uni" + _word(rng, 0, 9))
            rv, _ = self._check(self._run(app, pin))
            self.assertEqual(rv.replace("-", ""), pin.replace("-", ""))

    def test_machine_id_shapes(self):
        rng = random.Random(7)
        shapes = [None, b"", "", b"\x00" * 3]
        for i in range(8):
            machine = shapes[i % 4] if i < 4 else _word(rng, 1, 40).encode()
            app = make_app("func", self.modnames[(i * 5) % 8], _word(rng, 3, 9))
            rv, _ = self._check(self._run(app, None, machine=machine))
            self.assertEqual(len(rv), 11)

    def test_object_instance_apps(self):
        rng = random.Random(8)
        for i in range(7):
            name = "".join(w.capitalize() for w in (_word(rng, 1, 5) for _ in range(i % 4 + 1)))
            app = make_app("obj", self.modnames[(7 - i) % 8], name)
            pin = None if i % 2 else str(rng.randint(10 ** 6, 10 ** 11))
            rv, _ = self._check(self._run(app, pin, user=_word(rng, 1, 20)))
            self.assertIn("-", rv + "-")

    def test_class_apps_varied_nodes(self):
        rng = random.Random(9)
        for i in range(8):
            node = rng.choice([0, 7, rng.randint(1, 2 ** 48 - 1), 2 ** 47 + i])
            app = make_app("cls", self.modnames[i % 8], "K" * (i + 1))
            rv, _ = self._check(self._run(app, None, node=node))
            self.assertTrue(rv[0].isdigit())

    def test_empty_and_dash_only_pins(self):
        rng = random.Random(10)
        pins = ["", "-", "---", "-" * 5 + "x", " ", "12 34", "1_000", "+123"]
        for i, pin in enumerate(pins):
            app = make_app("func", self.modnames[(i * 7) % 8], _word(rng, 1, 18))
            rv, _ = self._check(self._run(app, pin, user=_word(rng, 0, 12)))
            self.assertNotEqual(rv, pin)

    def test_stability_across_repeated_calls(self):
        rng = random.Random(11)
        for i in range(5):
            app = make_app("func", self.modnames[i], _word(rng, 6, 12))
            first = self._run(app, None)
            second = self._run(app, None)
            self.assertEqual(first, second)
            self._check(first)

    def test_long_numeric_pins_with_mixed_separators(self):
        rng = random.Random(12)
        for i in range(7):
            digits = "".join(str(rng.randint(0, 9)) for _ in range(rng.randint(3, 20)))
            if i % 2:
                cut = rng.randint(1, len(digits) - 1)
                digits = digits[:cut] + "-" * (i % 3 + 1) + digits[cut:]
            app = make_app("obj", self.modnames[(i + 2) % 8], _word(rng, 1, 25))
            rv, _ = self._check(self._run(app, digits, machine=None if i % 3 == 0 else b"m" * i))
            self.assertEqual(rv.replace("-", ""), digits.replace("-", ""))
