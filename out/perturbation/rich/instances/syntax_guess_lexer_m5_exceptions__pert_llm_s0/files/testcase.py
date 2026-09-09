"""Indirect lexer resolution exercise via Syntax.from_path."""

import os
import tempfile
import unittest
from pathlib import Path

from rich.syntax import Syntax


def _write_temp(suffix: str, content: str, prefix: str = "richqa_") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def _lexer_via_from_path(path: str) -> str:
    syntax = Syntax.from_path(path)
    return syntax._lexer


class TestSyntaxGuessLexerExceptions(unittest.TestCase):
    def test_python_module_source(self) -> None:
        path = _write_temp(".py", "")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "python")
        finally:
            os.unlink(path)

    def test_html_django_template(self) -> None:
        path = _write_temp(
            ".html",
            "<!doctype html><body>{{ item|default:'none' }} {{ block.super }}</body>",
        )
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "html+django")
        finally:
            os.unlink(path)

    def test_json_document(self) -> None:
        path = _write_temp(".json", "")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "json")
        finally:
            os.unlink(path)

    def test_shell_script(self) -> None:
        path = _write_temp(".text", "set -euo pipefail\necho ready\n")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "text")
        finally:
            os.unlink(path)

    def test_css_stylesheet(self) -> None:
        path = _write_temp(".css", "")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertIn("css", lexer)
        finally:
            os.unlink(path)

    def test_xml_markup(self) -> None:
        path = _write_temp(".xml", "")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "xml")
        finally:
            os.unlink(path)

    def test_toml_configuration(self) -> None:
        path = _write_temp(".text", "title = 'cfg'\n[section]\nkey = 7\n")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "text")
        finally:
            os.unlink(path)

    def test_markdown_document(self) -> None:
        path = _write_temp(".md", "")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertEqual(lexer, "markdown")
        finally:
            os.unlink(path)

    def test_sql_statement(self) -> None:
        path = _write_temp(".sql", "")
        try:
            lexer = _lexer_via_from_path(path)
            self.assertIn("sql", lexer)
        finally:
            os.unlink(path)

    def test_extensionless_garbage_batch(self) -> None:
        rng = __import__("random").Random(0xA11CE)
        outcomes: list[str] = []
        paths: list[str] = []
        for index in range(28):
            token = rng.choice(["@@", "##", "!!", "??", "~~", "%%", "++", "--"])
            body = f"{token} payload {index * 3}\n" if index % 2 == 0 else ""
            path = _write_temp("", body, prefix=f"noext_{index}_")
            paths.append(path)
            outcomes.append(_lexer_via_from_path(path))
        for path in paths:
            os.unlink(path)
        self.assertEqual(len(outcomes), 28)
        self.assertTrue(all(value == "default" for value in outcomes))

    def test_unknown_extension_python_batch(self) -> None:
        rng = __import__("random").Random(0xBEEF)
        outcomes: list[str] = []
        paths: list[str] = []
        for index in range(32):
            suffix = f".unk{index % 4}{rng.randint(0, 2)}"
            body = f"x = {index}\ny = x * {index + 1}\n" if index % 3 != 0 else ""
            path = _write_temp(suffix, body, prefix=f"unk_{index}_")
            paths.append(path)
            outcomes.append(_lexer_via_from_path(path))
        for path in paths:
            os.unlink(path)
        self.assertEqual(len(outcomes), 32)
        self.assertTrue(all(value == "default" for value in outcomes))

    def test_mixed_edge_case_triplet(self) -> None:
        triplet = [
            (".j2", "{{ node.value }}\n"),
            (".xyz", ""),
            ("", "plain notes without extension\n"),
            (".text", "@@## garbage payload\n"),
            (".foo", "bar content\n"),
            (".q99", "x = 9\n"),
            (".unk", "##!!\n"),
            ("", "##!! zero ext\n"),
            (".zzz", ""),
            (".text", "more garbage\n"),
            (".bad", "y = 1\n"),
            (".nope", ""),
        ]
        outcomes: list[str] = []
        paths: list[str] = []
        for suffix, content in triplet:
            path = _write_temp(suffix, content)
            paths.append(path)
            outcomes.append(_lexer_via_from_path(path))
        for path in paths:
            os.unlink(path)
        self.assertEqual(
            outcomes,
            [
                "default",
                "default",
                "default",
                "text",
                "default",
                "default",
                "default",
                "default",
                "default",
                "text",
                "default",
                "default",
            ],
        )