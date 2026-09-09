import random
import unittest

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.simplify import simplify


class TestSimplifyBinaryControlFlow(unittest.TestCase):
    def _run_cases(self, sql_cases, dialect=None):
        results = [
            simplify(sqlglot.parse_one(sql, read=dialect), dialect=dialect) for sql in sql_cases
        ]
        self.assertTrue(results)
        self.assertTrue(all(isinstance(result, exp.Expr) and result.sql() for result in results))

    def test_generated_additions(self):
        rng = random.Random(104729)
        self._run_cases(
            f"{rng.randrange(1, 90)} + {rng.randrange(1, 90)} + {rng.randrange(1, 90)}"
            for _ in range(19)
        )

    def test_generated_products(self):
        rng = random.Random(130363)
        self._run_cases(
            f"{rng.randrange(2, 13)} * {rng.randrange(2, 17)} * {rng.randrange(2, 19)}"
            for _ in range(17)
        )

    def test_generated_subtractions(self):
        rng = random.Random(155921)
        self._run_cases(
            f"({rng.randrange(40, 150)} - {rng.randrange(1, 35)}) - {rng.randrange(1, 20)}"
            for _ in range(18)
        )

    def test_mixed_divisions(self):
        rng = random.Random(179424673)
        cases = []
        for index in range(20):
            numerator = rng.randrange(20, 200)
            denominator = rng.randrange(2, 12)
            if index % 3:
                cases.append(f"{numerator}.{index % 7 + 1} / {denominator}.0")
            else:
                cases.append(f"{numerator} / {denominator}")
        self._run_cases(cases)

    def test_numeric_predicates(self):
        rng = random.Random(2038074743)
        operators = ("=", "<>", "<", "<=", ">", ">=")
        self._run_cases(
            f"{rng.randrange(-30, 70)} {operators[index % len(operators)]} "
            f"{rng.randrange(-30, 70)}"
            for index in range(24)
        )

    def test_string_predicates(self):
        rng = random.Random(22801763489)
        operators = ("=", "<>", "<", ">")
        cases = []
        for index in range(16):
            left = chr(97 + rng.randrange(0, 20)) * (1 + index % 4)
            right = chr(102 + rng.randrange(0, 20)) * (1 + (index + 1) % 4)
            cases.append(f"'{left}' {operators[index % len(operators)]} '{right}'")
        self._run_cases(cases)

    def test_is_null_forms(self):
        rng = random.Random(2521008887)
        cases = []
        for index in range(18):
            operand = "NULL" if index % 3 == 0 else str(rng.randrange(1, 80))
            suffix = "IS NOT NULL" if index % 2 else "IS NULL"
            cases.append(f"{operand} {suffix}")
        self._run_cases(cases)

    def test_null_safe_predicates(self):
        rng = random.Random(275604541)
        cases = []
        for index in range(16):
            left = "NULL" if index % 4 == 0 else str(rng.randrange(1, 60))
            right = "NULL" if index % 5 == 0 else str(rng.randrange(1, 60))
            cases.append(f"{left} <=> {right}")
        self._run_cases(cases, dialect="mysql")

    def test_nulls_in_conditionals(self):
        rng = random.Random(29996224275833)
        self._run_cases(
            f"IF(NULL + {rng.randrange(1, 50)}, 'left_{index}', 'right_{index}')"
            for index in range(17)
        )

    def test_date_interval_arithmetic(self):
        rng = random.Random(32416190071)
        cases = []
        for index in range(20):
            year = 2011 + rng.randrange(0, 12)
            month = 1 + rng.randrange(0, 12)
            day = 1 + rng.randrange(0, 20)
            amount = 1 + rng.randrange(0, 8)
            operator = "+" if index % 2 else "-"
            cases.append(
                f"DATE '{year:04d}-{month:02d}-{day:02d}' {operator} INTERVAL '{amount}' DAY"
            )
        self._run_cases(cases)

    def test_interval_date_additions(self):
        rng = random.Random(3486784401)
        self._run_cases(
            "INTERVAL '{amount}' DAY + DATE '{year:04d}-{month:02d}-{day:02d}'".format(
                amount=1 + rng.randrange(0, 6),
                year=2010 + rng.randrange(0, 14),
                month=1 + rng.randrange(0, 12),
                day=1 + rng.randrange(0, 20),
            )
            for _ in range(16)
        )

    def test_date_and_cast_comparisons(self):
        rng = random.Random(373939777)
        operators = ("=", "<>", "<", ">=", "<=", ">")
        cases = []
        for index in range(22):
            if index % 2:
                left_day = 1 + rng.randrange(0, 20)
                right_day = 1 + rng.randrange(0, 20)
                cases.append(
                    f"DATE '2021-04-{left_day:02d}' {operators[index % len(operators)]} "
                    f"DATE '2021-04-{right_day:02d}'"
                )
            else:
                left = rng.randrange(-120, 260)
                right = rng.randrange(-120, 260)
                cases.append(
                    f"CAST({left} AS SMALLINT) {operators[index % len(operators)]} "
                    f"CAST({right} AS INTEGER)"
                )
        self._run_cases(cases)
