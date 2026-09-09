import unittest

from sqlglot import expressions as exp
from sqlglot.optimizer.simplify import Simplifier


class TestSimplifyComparisonExceptions(unittest.TestCase):
    def test_generated_comparisons_then_malformed_number(self):
        simplifier = Simplifier(annotate_new_expressions=False)
        operators = (exp.LT, exp.LTE, exp.GT, exp.GTE, exp.EQ, exp.NEQ)
        outcomes = []
        state = 37

        for index in range(28):
            state = (state * 73 + index * 19 + 11) % 997
            column = exp.column(f"metric_{state % 9}")
            left_operator = operators[(state + index) % len(operators)]
            right_operator = operators[(state // 7 + index * 3) % len(operators)]
            connector = exp.Or() if state % 3 == 0 else exp.And()

            if index % 7 == 0:
                left = left_operator(this=column.copy(), expression=column.copy())
                right = right_operator(this=column.copy(), expression=column.copy())
            elif index % 5 == 0:
                month = state % 12 + 1
                day = (state // 12) % 27 + 1
                other_day = day % 27 + 1
                left_value = exp.cast(
                    exp.Literal.string(f"20{index % 10:02d}-{month:02d}-{day:02d}"),
                    "DATE",
                )
                right_value = exp.cast(
                    exp.Literal.string(f"20{index % 10:02d}-{month:02d}-{other_day:02d}"),
                    "DATE",
                )
                left = left_operator(this=column.copy(), expression=left_value)
                right = right_operator(this=column.copy(), expression=right_value)
            elif index % 4 == 0:
                left = left_operator(
                    this=column.copy(), expression=exp.Literal.string(chr(97 + state % 26) * 3)
                )
                right = right_operator(
                    this=column.copy(),
                    expression=exp.Literal.string(chr(97 + (state + index) % 26) * 3),
                )
            else:
                left = left_operator(
                    this=column.copy(), expression=exp.Literal.number(str(state - 500))
                )
                right = right_operator(
                    this=column.copy(),
                    expression=exp.Literal.number(str((state * (index + 3)) % 1201 - 600)),
                )

            outcomes.append(
                simplifier._simplify_comparison(
                    connector, left, right, or_=isinstance(connector, exp.Or)
                )
            )

        self.assertEqual(len(outcomes), 28)
        self.assertTrue(any(outcome is None for outcome in outcomes))
        self.assertTrue(any(isinstance(outcome, exp.Expression) for outcome in outcomes))

        letters = []
        for offset in range(23):
            state = (state * 41 + offset * 17 + 29) % 4093
            letters.append(chr(103 + state % 17))
        malformed = "".join(letters)
        column = exp.column(f"metric_{state % 9}")
        left = exp.LT(this=column.copy(), expression=exp.Literal.number(malformed))
        right = exp.LTE(
            this=column.copy(), expression=exp.Literal.number(str(state % 101 + 1))
        )

        with self.assertRaises(BaseException):
            simplifier._simplify_comparison(exp.And(), left, right)
