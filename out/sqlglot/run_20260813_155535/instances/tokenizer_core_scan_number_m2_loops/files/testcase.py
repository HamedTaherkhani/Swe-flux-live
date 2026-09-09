import random
import unittest

import sqlglot
from sqlglot.tokens import TokenType


class TestScanNumberLoopBehavior(unittest.TestCase):
    def assert_tokenizes(self, sql, dialect):
        tokens = sqlglot.tokenize(sql, read=dialect)
        self.assertTrue(tokens)
        self.assertEqual(tokens[0].token_type, TokenType.SELECT)

    @staticmethod
    def underscore_number(rng, segments):
        return "_".join(
            str(rng.randrange(1, 10 ** rng.randrange(1, 5))) for _ in range(segments)
        )

    def test_01_duckdb_underscore_waves(self):
        rng = random.Random("duckdb-underscore-waves")
        values = [
            self.underscore_number(rng, 4 + rng.randrange(20))
            for _ in range(18 + rng.randrange(9))
        ]
        self.assert_tokenizes("SELECT " + ", ".join(values), "duckdb")

    def test_02_clickhouse_digit_identifiers(self):
        rng = random.Random("clickhouse-digit-identifiers")
        values = []
        for index in range(17 + rng.randrange(8)):
            prefix = self.underscore_number(rng, 3 + rng.randrange(17))
            suffix = "".join(chr(ord("a") + rng.randrange(26)) for _ in range(2 + index % 7))
            values.append(f"{prefix}{suffix}")
        self.assert_tokenizes("SELECT " + ", ".join(values), "clickhouse")

    def test_03_duckdb_scientific_mixture(self):
        rng = random.Random("duckdb-scientific-mixture")
        values = []
        for index in range(19 + rng.randrange(11)):
            whole = self.underscore_number(rng, 2 + rng.randrange(10))
            fraction = rng.randrange(10 ** (2 + index % 4))
            exponent = rng.randrange(1, 10 ** (1 + index % 3))
            sign = "+" if rng.randrange(2) else "-"
            values.append(f"{whole}.{fraction}e{sign}{exponent}")
        self.assert_tokenizes("SELECT " + ", ".join(values), "duckdb")

    def test_04_hive_numeric_suffixes(self):
        rng = random.Random("hive-numeric-suffixes")
        suffixes = ("L", "S", "Y", "D", "F", "BD")
        values = []
        for index in range(21 + rng.randrange(7)):
            digits = "".join(str(rng.randrange(10)) for _ in range(2 + rng.randrange(13)))
            values.append(digits + suffixes[(index + rng.randrange(len(suffixes))) % len(suffixes)])
        self.assert_tokenizes("SELECT " + ", ".join(values), "hive")

    def test_05_spark_suffix_and_exponents(self):
        rng = random.Random("spark-suffix-and-exponents")
        suffixes = ("L", "S", "Y", "D", "F", "BD")
        values = []
        for index in range(16 + rng.randrange(12)):
            base = rng.randrange(10 ** (2 + index % 6))
            if index % 3:
                values.append(f"{base}e{rng.choice(('-', '+'))}{rng.randrange(1, 900)}")
            else:
                values.append(f"{base}{rng.choice(suffixes)}")
        self.assert_tokenizes("SELECT " + ", ".join(values), "spark")

    def test_06_mysql_alphanumeric_boundaries(self):
        rng = random.Random("mysql-alphanumeric-boundaries")
        values = []
        for index in range(20 + rng.randrange(10)):
            digits = "".join(str(rng.randrange(10)) for _ in range(1 + rng.randrange(12)))
            tail = "".join(rng.choice("abcdefxyz") for _ in range(1 + index % 9))
            values.append(digits + tail)
        self.assert_tokenizes("SELECT " + ", ".join(values), "mysql")

    def test_07_postgres_bit_hex_and_decimal(self):
        rng = random.Random("postgres-bit-hex-and-decimal")
        values = []
        for index in range(24 + rng.randrange(9)):
            if index % 4 == 0:
                values.append("0x" + format(rng.randrange(1 << (5 + index % 8)), "x"))
            elif index % 4 == 1:
                values.append("0b" + format(rng.randrange(1 << (4 + index % 7)), "b"))
            else:
                values.append(f"{rng.randrange(10 ** 8)}.{rng.randrange(10 ** 6)}")
        self.assert_tokenizes("SELECT " + ", ".join(values), "postgres")

    def test_08_tsql_decimal_boundaries(self):
        rng = random.Random("tsql-decimal-boundaries")
        values = []
        for index in range(18 + rng.randrange(13)):
            left = rng.randrange(10 ** (1 + index % 7))
            right = rng.randrange(10 ** (1 + (index * 3) % 6))
            exponent = rng.randrange(1, 700)
            values.append(f"{left}.{right}E{rng.choice(('-', '+'))}{exponent}")
        self.assert_tokenizes("SELECT " + ", ".join(values), "tsql")

    def test_09_bigquery_generated_measurements(self):
        rng = random.Random("bigquery-generated-measurements")
        values = []
        accumulator = rng.randrange(2, 97)
        for index in range(23 + rng.randrange(10)):
            accumulator = (accumulator * rng.randrange(3, 31) + index) % (10 ** (3 + index % 5))
            scale = rng.randrange(10 ** (1 + index % 5))
            values.append(f"{accumulator}.{scale}e{index % 9}")
        self.assert_tokenizes("SELECT " + ", ".join(values), "bigquery")

    def test_10_sqlite_incomplete_scientific_forms(self):
        rng = random.Random("sqlite-incomplete-scientific-forms")
        separators = ("+", "-", ",", " ", ")")
        values = []
        for index in range(17 + rng.randrange(14)):
            digits = "".join(str(rng.randrange(10)) for _ in range(2 + rng.randrange(16)))
            values.append(digits + "e" + separators[index % len(separators)])
        self.assert_tokenizes("SELECT " + " ".join(values), "sqlite")

    def test_11_oracle_long_digit_batches(self):
        rng = random.Random("oracle-long-digit-batches")
        values = []
        for index in range(22 + rng.randrange(8)):
            width = 18 + (index * rng.randrange(2, 11)) % 73
            values.append("".join(str(rng.randrange(10)) for _ in range(width)))
        self.assert_tokenizes("SELECT " + ", ".join(values), "oracle")

    def test_12_snowflake_mixed_numeric_stream(self):
        rng = random.Random("snowflake-mixed-numeric-stream")
        values = []
        for index in range(26 + rng.randrange(9)):
            digits = "".join(str(rng.randrange(10)) for _ in range(1 + rng.randrange(15)))
            if index % 5 == 0:
                values.append("0x" + digits)
            elif index % 5 == 1:
                values.append(f"{digits}.{rng.randrange(10 ** 7)}")
            elif index % 5 == 2:
                values.append(f"{digits}e-{rng.randrange(1, 500)}")
            elif index % 5 == 3:
                values.append(digits + rng.choice(("abc", "XYZ", "nan")))
            else:
                values.append(digits)
        self.assert_tokenizes("SELECT " + ", ".join(values), "snowflake")
