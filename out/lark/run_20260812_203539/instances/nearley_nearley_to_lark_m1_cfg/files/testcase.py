import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from lark.tools.nearley import create_code_for_nearley_grammar


def _rule_wave(size, step, offset=0):
    letters = "abcdefghijklm"
    statements = []
    for index in range(size):
        name = f"r_{offset}_{index}"
        token = letters[(index * step + offset) % len(letters)]
        if index % len("quartet") == 0:
            statements.append(f'{name} -> "{token}" | null')
        elif index % len("triple") == 0:
            statements.append(f'{name} -> "{token}":+')
        else:
            statements.append(f'{name} -> "{token}"')
    return statements


def _mixed_wave(size, step):
    statements = []
    for index, rule in enumerate(_rule_wave(size, step, step)):
        if index % len("octave") == 1:
            statements.append(f"@{{% var marker_{index} = {index % len('cycle')}; %}}")
        elif index % len("nonet") == 2:
            statements.append(f'macro_{index}[X] -> "m"')
        statements.append(rule)
    return statements


class TestNearleyConversionControlFlow(unittest.TestCase):
    def _convert(self, root_lines, includes=None, builtins=None, es6=False):
        includes = includes or {}
        builtins = builtins or {}
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source_dir = base / "source"
            builtin_dir = base / "builtin"
            source_dir.mkdir()
            builtin_dir.mkdir()
            for relative, lines in sorted(includes.items()):
                path = source_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(lines), encoding="utf-8")
            for relative, lines in sorted(builtins.items()):
                path = builtin_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(lines), encoding="utf-8")

            translator = "translated_marker = None\n"
            fake_js2py = types.ModuleType("js2py")
            fake_js2py.translate_js = lambda source: translator
            fake_js2py.translate_js6 = lambda source: translator
            with patch.dict(sys.modules, {"js2py": fake_js2py}):
                code = create_code_for_nearley_grammar(
                    "\n".join(root_lines),
                    "r_0_0",
                    str(builtin_dir),
                    str(source_dir),
                    es6=es6,
                )
        self.assertIn("translated_marker", code)
        self.assertIn("TransformNearley", code)
        return code

    def test_dense_rules_stride_two(self):
        code = self._convert(_rule_wave(len("densecontrolprofile"), 2))
        self.assertGreater(len(code), len("substantial"))

    def test_dense_rules_stride_five(self):
        code = self._convert(_rule_wave(len("alternatebranchvolume"), 5, 3))
        self.assertTrue(code.startswith("from lark"))

    def test_js_and_macro_interleave(self):
        code = self._convert(_mixed_wave(len("interleavedstatements"), 4))
        self.assertIn("grammar =", code)

    def test_es6_translation_route(self):
        lines = _mixed_wave(len("modernsyntaxrouting"), 7)
        code = self._convert(lines, es6=True)
        self.assertIn("def parse", code)

    def test_single_include_with_mixed_child(self):
        child = _mixed_wave(len("childstatementvolume"), 3)
        root = ['@include "child.ne"'] + _rule_wave(len("rootstatementspan"), 6)
        code = self._convert(root, {"child.ne": child})
        self.assertIn("parser = Lark", code)

    def test_duplicate_include_is_suppressed(self):
        child = _rule_wave(len("duplicatechildwave"), 4, 2)
        root = [
            '@include "repeat.ne"',
            '@include "repeat.ne"',
            *_mixed_wave(len("duplicaterootwave"), 5),
        ]
        code = self._convert(root, {"repeat.ne": child})
        self.assertGreater(code.count("!n_"), 0)

    def test_nested_relative_include_chain(self):
        leaf = _mixed_wave(len("nestedleafprofile"), 2)
        middle = ['@include "deep/leaf.ne"', *_rule_wave(len("middlewave"), 3, 1)]
        root = ['@include "middle.ne"', *_rule_wave(len("nestedrootvolume"), 8)]
        code = self._convert(
            root,
            {
                "middle.ne": middle,
                "deep/leaf.ne": leaf,
            },
        )
        self.assertIn("__default__", code)

    def test_branching_include_graph(self):
        left = _mixed_wave(len("leftbranchvolume"), 3)
        right = _rule_wave(len("rightbranchvolume"), 5, 4)
        root = [
            '@include "left.ne"',
            '@include "right.ne"',
            *_rule_wave(len("branchingrootwave"), 7),
        ]
        code = self._convert(root, {"left.ne": left, "right.ne": right})
        self.assertTrue(code.endswith("\n"))

    def test_builtin_and_relative_mix(self):
        shared = _mixed_wave(len("builtinsharedprofile"), 6)
        local = _rule_wave(len("localincludeprofile"), 2, 5)
        root = [
            '@builtin "shared.ne"',
            '@include "local.ne"',
            *_rule_wave(len("mixedrootprofile"), 4),
        ]
        code = self._convert(
            root,
            {"local.ne": local},
            {"shared.ne": shared},
        )
        self.assertIn("translated_marker", code)

    def test_duplicate_builtin_across_recursion(self):
        shared = _rule_wave(len("sharedbuiltinwave"), 8, 6)
        child = [
            '@builtin "shared.ne"',
            *_mixed_wave(len("recursivechildwave"), 5),
        ]
        root = [
            '@builtin "shared.ne"',
            '@include "child.ne"',
            *_rule_wave(len("recursiverootwave"), 3),
        ]
        code = self._convert(
            root,
            {"child.ne": child},
            {"shared.ne": shared},
        )
        self.assertNotEqual(code, "")

    def test_js_heavy_root_with_include(self):
        child = _mixed_wave(len("javascriptchildprofile"), 7)
        root = _mixed_wave(len("javascriptrootprofile"), 2)
        root.insert(len(root) // 2, '@include "scripted.ne"')
        code = self._convert(root, {"scripted.ne": child})
        self.assertGreater(code.count("!n_"), len("wide"))

    def test_unknown_directive_exits_early(self):
        lines = _rule_wave(len("beforeinvaliddirective"), 3)
        lines.insert(len(lines) // 2, "@mystery unsupported")
        with self.assertRaises(AssertionError):
            self._convert(lines)
