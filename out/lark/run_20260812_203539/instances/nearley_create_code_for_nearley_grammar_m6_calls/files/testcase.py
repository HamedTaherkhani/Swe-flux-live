import random
import sys
import types
import unittest

from lark.tools.nearley import create_code_for_nearley_grammar


def _translated_javascript(source):
    checksum = sum((index + 1) * ord(char) for index, char in enumerate(source))
    return "var = {}  # translation-checksum=%s\n" % checksum


js2py_stub = types.ModuleType("js2py")
js2py_stub.translate_js = _translated_javascript
js2py_stub.translate_js6 = _translated_javascript
sys.modules["js2py"] = js2py_stub


class TestNearleyCodeGenerationDynamics(unittest.TestCase):
    def _case(self, seed, mode, width_text, use_es6=False):
        rng = random.Random((seed + 1) * len(width_text) * (mode + 3))
        width = len(width_text) + len("dynamic-workload")
        rules = []
        names = []

        if mode % 3 == 0:
            rules.append("@{% var shared = function(x) { return x; }; %}")

        for index in range(width):
            name = "unit_%s_%s" % (mode, index)
            names.append(name)
            choice = (rng.randrange(len("branching")) + index + seed + mode) % 7
            letter = chr(ord("a") + (index * (mode + 1) + seed) % len("alphabet"))

            if choice == 0:
                expression = '"%s"' % letter
            elif choice == 1:
                expression = "[%s-%s]" % (letter, chr(ord(letter) + 1))
            elif choice == 2:
                expression = "null"
            elif choice == 3:
                expression = '("%s" | "%s"):?' % (letter, letter.upper())
            elif choice == 4 and names[:-1]:
                expression = names[(index + seed) % len(names[:-1])] + ":+"
            elif choice == 5:
                expression = '"%s":*' % letter
            else:
                expression = '"%s" | [%s-%s]' % (
                    letter,
                    letter,
                    chr(ord(letter) + 1),
                )

            action = ""
            if (rng.randrange(len("actions")) + index + mode) % 4 != 0:
                action = " {% function(d) { return d[0]; } %}"
            rules.append("%s -> %s%s" % (name, expression, action))

            if index % (mode + 4) == 1:
                rules.append(
                    "macro_%s_%s[x] -> \"%s\"" % (mode, index, letter)
                )

        stride = 1 + mode % 4
        selected = names[mode % stride :: stride]
        rules.append(
            "main -> "
            + " ".join(selected)
            + " {% function(d) { return d; } %}"
        )
        if mode % 2:
            rules.append("main -> null")

        grammar = "\n".join(rules)
        code = create_code_for_nearley_grammar(
            grammar, "main", "/unused/builtin", "/unused/folder", es6=use_es6
        )

        self.assertIsInstance(code, str)
        self.assertGreater(len(code), len(grammar))
        self.assertIn("TransformNearley", code)
        self.assertIn("maybe_placeholders=False", code)
        compile(code, "<generated-nearley>", "exec")

    def test_dense_strings_and_actions(self):
        self._case(0, 0, "amber-field")

    def test_regex_and_optional_groups(self):
        self._case(1, 1, "blue-river")

    def test_null_and_repetition_mix(self):
        self._case(2, 2, "copper-grove")

    def test_top_level_javascript_mix(self):
        self._case(3, 3, "delta-harbor")

    def test_sparse_action_distribution(self):
        self._case(4, 4, "ember-island")

    def test_wide_reference_distribution(self):
        self._case(5, 5, "forest-junction")

    def test_alternative_start_rule(self):
        self._case(6, 6, "granite-keep")

    def test_nested_optional_distribution(self):
        self._case(7, 7, "hazel-lantern")

    def test_repeated_reference_distribution(self):
        self._case(8, 8, "indigo-meadow")

    def test_derived_seed_distribution(self):
        self._case(len("seed-nine") % len("modes"), 9, "juniper-night")

    def test_es6_translation_path(self):
        self._case(
            len("seed-ten") % len("modes"),
            len("abcdefghij"),
            "kelp-orchard",
            True,
        )

    def test_largest_generated_grammar(self):
        self._case(
            len("seed-eleven") % len("modes"),
            len("abcdefghijk"),
            "linen-prairie-wide",
        )
