import sys
import unittest

from lark.exceptions import GrammarError
from lark.load_grammar import PackageResource
from lark.load_grammar import list_grammar_imports
from lark.load_grammar import load_grammar as compile_grammar


TERMINALS = (
    "DIGIT",
    "HEXDIGIT",
    "INT",
    "SIGNED_INT",
    "DECIMAL",
    "FLOAT",
    "SIGNED_FLOAT",
    "NUMBER",
    "SIGNED_NUMBER",
    "ESCAPED_STRING",
    "LCASE_LETTER",
    "UCASE_LETTER",
    "LETTER",
    "WORD",
    "CNAME",
    "WS_INLINE",
    "WS",
    "CR",
    "LF",
    "NEWLINE",
    "SH_COMMENT",
    "CPP_COMMENT",
    "C_COMMENT",
    "SQL_COMMENT",
)


def _definitions():
    return "\n".join(f"{name}: /x+/" for name in TERMINALS)


def _memory_loader(base_path, grammar_path):
    normalized = grammar_path.replace("\\", "/")
    return f"memory/{normalized}", _definitions()


def _single_imports(names, prefix="common", aliases=False):
    lines = []
    for index, name in enumerate(names):
        suffix = f" -> IMPORTED_{index}_{name}" if aliases else ""
        lines.append(f"%import {prefix}.{name}{suffix}")
    return lines


def _multi_imports(names, prefix="common", width=4):
    return [
        f"%import {prefix} ({', '.join(names[offset:offset + width])})"
        for offset in range(0, len(names), width)
    ]


class TestGrammarImportControlFlow(unittest.TestCase):
    def _exercise_library(self, lines):
        imported = list_grammar_imports("\n".join(lines), [])
        self.assertEqual(len(imported), 1)
        self.assertTrue(imported[0])

    def _exercise_memory(self, lines):
        imported = list_grammar_imports("\n".join(lines), [_memory_loader])
        self.assertGreater(len(imported), 0)
        self.assertTrue(all(imported))

    def test_aliases_rotated_selection(self):
        amount = len("deterministicset")
        names = [TERMINALS[(index * 5 + 2) % len(TERMINALS)] for index in range(amount)]
        self._exercise_library(_single_imports(names, aliases=True))

    def test_external_source_mixed_imports(self):
        amount = len("externalgrammar")
        names = [TERMINALS[(index * 7 + 1) % len(TERMINALS)] for index in range(amount)]
        lines = _single_imports(names[::2], ".delta")
        lines += _single_imports(names[1::2], ".delta", aliases=True)
        grammar, used = compile_grammar(
            "\n".join(lines),
            "/virtual/project/root.lark",
            [_memory_loader],
            False,
        )
        self.assertTrue(grammar)
        self.assertGreater(len(used), 0)

    def test_library_duplicate_wave(self):
        amount = len("repeatedimportwave")
        names = [TERMINALS[(index * index + 3) % len(TERMINALS)] for index in range(amount)]
        lines = _single_imports(names)
        self._exercise_library(lines)

    def test_library_mixed_forms(self):
        amount = len("mixedcontrolflow")
        names = [TERMINALS[(index * 3 + 4) % len(TERMINALS)] for index in range(amount)]
        pivot = len(names) // 3
        lines = _single_imports(names[:pivot])
        lines += _single_imports(names[pivot : pivot * 2], aliases=True)
        lines += _multi_imports(names[pivot * 2 :], width=2)
        self._exercise_library(lines)

    def test_library_multi_groups(self):
        amount = len("groupedterminalimports")
        names = [TERMINALS[(index * 5) % len(TERMINALS)] for index in range(amount)]
        self._exercise_library(_multi_imports(names, width=3))

    def test_library_single_stride(self):
        amount = len("broadimportprofile")
        names = [TERMINALS[(index * 7) % len(TERMINALS)] for index in range(amount)]
        self._exercise_library(_single_imports(names))

    def test_missing_main_file_fallback(self):
        amount = len("fallbackdirectory")
        names = [TERMINALS[(index * 2 + 5) % len(TERMINALS)] for index in range(amount)]
        lines = _single_imports(names, ".epsilon")
        main_module = sys.modules["__main__"]
        marker = object()
        previous = getattr(main_module, "__file__", marker)
        if previous is not marker:
            delattr(main_module, "__file__")
        try:
            self._exercise_memory(lines)
        finally:
            if previous is not marker:
                setattr(main_module, "__file__", previous)

    def test_package_resource_source(self):
        amount = len("packageresource")
        names = [TERMINALS[(index * 4 + 1) % len(TERMINALS)] for index in range(amount)]
        lines = _single_imports(names[::2], ".zeta")
        lines += _multi_imports(names[1::2], ".zeta", width=2)
        grammar, used = compile_grammar(
            "\n".join(lines),
            PackageResource("sample_pkg", "grammars/root.lark"),
            [_memory_loader],
            False,
        )
        self.assertTrue(grammar)
        self.assertGreater(len(used), 0)

    def test_relative_aliases(self):
        amount = len("relativealiases")
        names = [TERMINALS[(index * 3 + 7) % len(TERMINALS)] for index in range(amount)]
        self._exercise_memory(_single_imports(names, ".beta", aliases=True))

    def test_relative_multi_groups(self):
        amount = len("relativegrouping")
        names = [TERMINALS[(index * 7 + 6) % len(TERMINALS)] for index in range(amount)]
        self._exercise_memory(_multi_imports(names, ".gamma", width=3))

    def test_relative_single_imports(self):
        amount = len("relativeimports")
        names = [TERMINALS[(index * 5 + 3) % len(TERMINALS)] for index in range(amount)]
        self._exercise_memory(_single_imports(names, ".alpha"))

    def test_rejected_empty_paths(self):
        amount = len("badpaths")
        names = [TERMINALS[(index * 3) % len(TERMINALS)] for index in range(amount)]
        for name in names:
            with self.assertRaises(GrammarError):
                list_grammar_imports(f"%import {name}", [])
