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
        code = self._convert(_rule_wave(len("densecontrolprofileexpandedmax"), 3))
        self.assertGreater(len(code), len("substantial"))

    def test_dense_rules_stride_five(self):
        code = self._convert(_rule_wave(len("alternatebranchvolumemaximizedprofile"), 11, 7))
        self.assertTrue(code.startswith("from lark"))

    def test_js_and_macro_interleave(self):
        code = self._convert(_mixed_wave(len("interleavedstatementsprofilemax"), 9))
        self.assertIn("grammar =", code)

    def test_es6_translation_route(self):
        lines = _mixed_wave(len("modernsyntaxroutingextendedprofile"), 13)
        code = self._convert(lines, es6=True)
        self.assertIn("def parse", code)

    def test_single_include_with_mixed_child(self):
        child = ['@include "nested/grandchild.ne"', *_mixed_wave(len("childstatementvolumeexpanded"), 7)]
        root = ['@include "child.ne"'] + _rule_wave(len("rootstatementspanextended"), 11)
        code = self._convert(
            root,
            {
                "child.ne": child,
                "nested/grandchild.ne": _rule_wave(len("grandchildstatementvolume"), 5, 2),
            },
        )
        self.assertIn("parser = Lark", code)

    def test_duplicate_include_is_suppressed(self):
        child = _rule_wave(len("duplicatechildwaveexpandedmax"), 6, 4)
        root = [
            '@include "repeat.ne"',
            '@include "repeat.ne"',
            *_mixed_wave(len("duplicaterootwaveexpandedmax"), 8),
        ]
        code = self._convert(root, {"repeat.ne": child})
        self.assertGreater(code.count("!n_"), 0)

    def test_nested_relative_include_chain(self):
        leaf = _mixed_wave(len("nestedleafprofileextendedmax"), 5)
        middle = [
            '@include "deep/leaf.ne"',
            '@include "deep/aux.ne"',
            *_rule_wave(len("middlewaveextendedmax"), 7, 3),
        ]
        root = ['@include "middle.ne"', *_rule_wave(len("nestedrootvolumeexpandedmax"), 13)]
        code = self._convert(
            root,
            {
                "middle.ne": middle,
                "deep/leaf.ne": leaf,
                "deep/aux.ne": _rule_wave(len("nestedauxprofile"), 4, 1),
            },
        )
        self.assertIn("__default__", code)

    def test_branching_include_graph(self):
        left = ['@include "left/deep.ne"', *_mixed_wave(len("leftbranchvolumeexpandedmax"), 7)]
        right = ['@include "right/leaf.ne"', *_rule_wave(len("rightbranchvolumeexpandedmax"), 9, 6)]
        root = [
            '@include "left.ne"',
            '@include "right.ne"',
            *_rule_wave(len("branchingrootwaveexpandedmax"), 12),
        ]
        code = self._convert(
            root,
            {
                "left.ne": left,
                "left/deep.ne": _mixed_wave(len("leftdeepbranchvolume"), 4),
                "right.ne": right,
                "right/leaf.ne": _rule_wave(len("rightleafbranchvolume"), 3, 2),
            },
        )
        self.assertTrue(code.endswith("\n"))

    def test_builtin_and_relative_mix(self):
        shared = [
            '@include "shared/leaf.ne"',
            *_mixed_wave(len("builtinsharedprofileexpandedmax"), 10),
        ]
        local = ['@include "local/inner.ne"', *_rule_wave(len("localincludeprofileexpandedmax"), 5, 9)]
        root = [
            '@builtin "shared.ne"',
            '@include "local.ne"',
            *_rule_wave(len("mixedrootprofileexpandedmax"), 8),
        ]
        code = self._convert(
            root,
            {
                "local.ne": local,
                "local/inner.ne": _mixed_wave(len("localinnerprofile"), 3),
            },
            {
                "shared.ne": shared,
                "shared/leaf.ne": _rule_wave(len("builtinsharedleafprofile"), 3, 1),
            },
        )
        self.assertIn("translated_marker", code)

    def test_duplicate_builtin_across_recursion(self):
        shared = _rule_wave(len("sharedbuiltinwaveexpandedmax"), 12, 8)
        child = [
            '@builtin "shared.ne"',
            '@include "child/inner.ne"',
            *_mixed_wave(len("recursivechildwaveexpandedmax"), 9),
        ]
        root = [
            '@builtin "shared.ne"',
            '@include "child.ne"',
            *_rule_wave(len("recursiverootwaveexpandedmax"), 7),
        ]
        code = self._convert(
            root,
            {
                "child.ne": child,
                "child/inner.ne": _rule_wave(len("recursiveinnerwave"), 4, 3),
            },
            {"shared.ne": shared},
        )
        self.assertNotEqual(code, "")

    def test_js_heavy_root_with_include(self):
        child = _mixed_wave(len("javascriptchildprofileexpandedmax"), 11)
        root = _mixed_wave(len("javascriptrootprofileexpandedmax"), 6)
        root.insert(len(root) // 2, '@include "scripted.ne"')
        code = self._convert(root, {"scripted.ne": child})
        self.assertGreater(code.count("!n_"), len("wide"))

    def test_unknown_directive_exits_early(self):
        lines = _rule_wave(len("beforeinvaliddirectiveexpandedmax"), 5)
        lines.insert(len(lines) // 2, "@mystery unsupported")
        with self.assertRaises(AssertionError):
            self._convert(lines)