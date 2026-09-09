import random
import unittest

from sqlglot import Dialect
from sqlglot.tokens import TokenType


class TestTokenizerStringDataFlow(unittest.TestCase):
    def _tokenize(self, dialect, fragments):
        sql = "SELECT " + ", ".join(fragments)
        tokens = Dialect.get_or_raise(dialect).tokenize(sql)
        string_types = {
            TokenType.BYTE_STRING,
            TokenType.HEREDOC_STRING,
            TokenType.RAW_STRING,
            TokenType.STRING,
        }
        self.assertTrue(tokens)
        self.assertTrue(any(token.token_type in string_types for token in tokens))

    def test_simple_generated_literals(self):
        fragments = [f"'alpha_{i}_{(i * i + 3) % 7}'" for i in range(3 * 7)]
        self._tokenize("", fragments)

    def test_doubled_quote_runs(self):
        fragments = [
            "'" + "''".join(f"part_{i}_{j}" for j in range(2 + i % 4)) + "'"
            for i in range(4 * 5)
        ]
        self._tokenize("", fragments)

    def test_mysql_custom_escapes(self):
        rng = random.Random(7 * 19)
        escaped = ("n", "t", "0", "%", "_", "Z")
        fragments = []
        for i in range(3 * 8):
            pieces = [f"m{i}"]
            pieces.extend("\\" + escaped[rng.randrange(len(escaped))] for _ in range(2 + i % 5))
            fragments.append("'" + "".join(pieces) + "'")
        self._tokenize("mysql", fragments)

    def test_clickhouse_unescaped_sequences(self):
        fragments = [
            "'" + "".join(f"c{i}_{j}\\0\\n" for j in range(1 + i % 4)) + "'"
            for i in range(5 * 4)
        ]
        self._tokenize("clickhouse", fragments)

    def test_bigquery_triple_quotes(self):
        fragments = []
        for i in range(2 * 9):
            body = "\n".join(f"triple_{i}_{j}\\'q" for j in range(1 + i % 5))
            fragments.append("'''" + body + "'''")
        self._tokenize("bigquery", fragments)

    def test_bigquery_raw_triples(self):
        rng = random.Random(11 * 23)
        fragments = []
        for i in range(4 * 5):
            body = "".join(f"r{rng.randrange(8)}\\n" for _ in range(2 + i % 6))
            fragments.append("r'''" + body + "'''")
        self._tokenize("bigquery", fragments)

    def test_bigquery_byte_literals(self):
        fragments = [
            "b'" + "".join(f"b{i}_{j}\\t" for j in range(2 + i % 4)) + "'"
            for i in range(3 * 6)
        ]
        self._tokenize("bigquery", fragments)

    def test_spark_raw_literals(self):
        fragments = [
            "r'" + "".join(f"s{i}_{j}\\n" for j in range(3 + i % 5)) + "'"
            for i in range(2 * 10)
        ]
        self._tokenize("spark", fragments)

    def test_snowflake_dollar_and_quotes(self):
        fragments = []
        for i in range(3 * 7):
            body = "".join(f"snow_{i}_{j}\\a" for j in range(1 + i % 5))
            fragments.append(f"$${body}$$")
            fragments.append("'" + body.replace("snow", "sn''ow") + "'")
        self._tokenize("snowflake", fragments)

    def test_postgres_tagged_heredocs(self):
        fragments = []
        for i in range(4 * 5):
            tag = f"tag{i % 7}"
            body = "\n".join(f"pg_{i}_{j}'\\x" for j in range(2 + i % 4))
            fragments.append(f"${tag}${body}${tag}$")
        self._tokenize("postgres", fragments)

    def test_duckdb_untagged_heredocs(self):
        fragments = [
            "$$" + "\n".join(f"duck_{i}_{j}\\z" for j in range(1 + i % 6)) + "$$"
            for i in range(3 * 6)
        ]
        self._tokenize("duckdb", fragments)

    def test_quoted_identifiers_and_multiline_strings(self):
        identifiers = [
            '"' + '""'.join(f"id_{i}_{j}" for j in range(2 + i % 3)) + '"'
            for i in range(2 * 9)
        ]
        literals = [
            "'" + "\n".join(f"line_{i}_{j}''tail" for j in range(2 + i % 5)) + "'"
            for i in range(2 * 9)
        ]
        sql = "SELECT " + ", ".join(
            f"{literal} AS {identifier}" for literal, identifier in zip(literals, identifiers)
        )
        tokens = Dialect.get_or_raise("").tokenize(sql)
        self.assertTrue(tokens)
        self.assertTrue(any(token.token_type == TokenType.IDENTIFIER for token in tokens))

    def test_unmatched_generated_literal(self):
        body = "".join(f"open_{i}_{(i * 5 + 2) % 9}" for i in range(3 * 9))
        with self.assertRaises(Exception):
            Dialect.get_or_raise("").tokenize("SELECT '" + body)
