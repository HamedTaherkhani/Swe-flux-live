import random
import unittest

from sqlglot import exp
from sqlglot.dialects.snowflake import Snowflake
from sqlglot.parsers.snowflake import _build_datetime


class TestSnowflakeDatetimeBuilderControlFlow(unittest.TestCase):
    def setUp(self):
        self.dialect = Snowflake()

    def _run_generated(self, seed, modes):
        rng = random.Random(seed)
        expected_types = {
            "date_cast": exp.Cast,
            "safe_date_cast": exp.TryCast,
            "time_cast": exp.Cast,
            "timestamp_unix": exp.UnixToTime,
            "timestamp_scale": exp.UnixToTime,
            "timestamp_format": exp.StrToTime,
            "safe_timestamp_format": exp.StrToTime,
            "date_format": exp.TsOrDsToDate,
            "time_format": exp.TsOrDsToTime,
            "date_numeric": exp.Anonymous,
            "safe_timestamp_numeric": exp.Anonymous,
            "timestamp_column": exp.Anonymous,
            "date_column_format": exp.TsOrDsToDate,
            "time_column_format": exp.TsOrDsToTime,
        }
        results = []
        accumulator = seed
        total = len(modes) * len("cfg") + len("branches") + seed % len("paths")

        for index in range(total):
            accumulator = (accumulator * len("snowflake") + index + rng.randrange(1, 97)) % 10007
            mode = modes[(accumulator + index) % len(modes)]
            number = accumulator + index + 1
            date_text = f"{2000 + number % 25:04d}-{1 + number % 12:02d}-{1 + number % 27:02d}"
            time_text = f"{number % 24:02d}:{number % 60:02d}:{(number * 3) % 60:02d}"
            format_text = ("YYYY", "-", "MM", "-", "DD") if index % 2 else ("DD", "/", "MM", "/", "YYYY")
            fmt = exp.Literal.string("".join(format_text))

            if mode == "date_cast":
                config = ("TO_DATE", exp.DType.DATE, False, [exp.Literal.string(date_text)])
            elif mode == "safe_date_cast":
                config = ("TRY_TO_DATE", exp.DType.DATE, True, [exp.Literal.string(date_text)])
            elif mode == "time_cast":
                config = ("TO_TIME", exp.DType.TIME, False, [exp.Literal.string(time_text)])
            elif mode == "timestamp_unix":
                value = exp.Literal.string(str(number)) if index % 2 else exp.Literal.number(number)
                config = ("TO_TIMESTAMP", exp.DType.TIMESTAMP, False, [value])
            elif mode == "timestamp_scale":
                value = exp.Neg(this=exp.Literal.number(number)) if index % 3 == 0 else exp.Literal.number(number)
                config = (
                    "TO_TIMESTAMP_NTZ",
                    exp.DType.TIMESTAMPNTZ,
                    False,
                    [value, exp.Literal.number(index % 7)],
                )
            elif mode == "timestamp_format":
                value = exp.Literal.string(date_text) if index % 2 else exp.column(f"ts_{number % 11}")
                config = ("TO_TIMESTAMP_TZ", exp.DType.TIMESTAMPTZ, False, [value, fmt])
            elif mode == "safe_timestamp_format":
                config = (
                    "TRY_TO_TIMESTAMP_LTZ",
                    exp.DType.TIMESTAMPLTZ,
                    True,
                    [exp.Literal.string(date_text), fmt],
                )
            elif mode == "date_format":
                value = exp.Literal.number(number) if index % 2 else exp.Literal.string(date_text)
                config = ("TO_DATE", exp.DType.DATE, False, [value, fmt])
            elif mode == "time_format":
                value = exp.column(f"clock_{number % 13}") if index % 2 else exp.Literal.string(time_text)
                config = ("TRY_TO_TIME", exp.DType.TIME, True, [value, fmt])
            elif mode == "date_numeric":
                config = ("TO_DATE", exp.DType.DATE, False, [exp.Literal.number(number)])
            elif mode == "safe_timestamp_numeric":
                config = (
                    "TRY_TO_TIMESTAMP",
                    exp.DType.TIMESTAMP,
                    True,
                    [exp.Literal.number(number)],
                )
            elif mode == "timestamp_column":
                config = (
                    "TO_TIMESTAMP",
                    exp.DType.TIMESTAMP,
                    False,
                    [exp.column(f"epoch_{number % 17}")],
                )
            elif mode == "date_column_format":
                config = (
                    "TRY_TO_DATE",
                    exp.DType.DATE,
                    True,
                    [exp.column(f"day_{number % 19}"), fmt],
                )
            else:
                config = (
                    "TO_TIME",
                    exp.DType.TIME,
                    False,
                    [exp.column(f"time_{number % 23}"), fmt],
                )

            name, kind, safe, args = config
            result = _build_datetime(name, kind, safe=safe)(args, self.dialect)
            self.assertIsInstance(result, expected_types[mode])
            results.append(result)

        self.assertEqual(len(results), total)
        self.assertTrue(all(result.parent is None for result in results))

    def test_cast_focused_rotation(self):
        self._run_generated(2, ("date_cast", "safe_date_cast", "time_cast"))

    def test_timestamp_numeric_rotation(self):
        self._run_generated(3, ("timestamp_unix", "timestamp_scale", "safe_timestamp_numeric"))

    def test_timestamp_format_rotation(self):
        self._run_generated(
            5, ("timestamp_format", "safe_timestamp_format", "timestamp_column")
        )

    def test_date_path_rotation(self):
        self._run_generated(7, ("date_cast", "date_format", "date_numeric", "date_column_format"))

    def test_time_path_rotation(self):
        self._run_generated(1, ("time_cast", "time_format", "time_column_format"))

    def test_safe_path_rotation(self):
        self._run_generated(
            4, ("safe_date_cast", "safe_timestamp_format", "safe_timestamp_numeric", "time_format")
        )

    def test_unsafe_path_rotation(self):
        self._run_generated(
            6, ("date_cast", "timestamp_unix", "timestamp_format", "time_column_format")
        )

    def test_literal_path_rotation(self):
        self._run_generated(
            8, ("date_cast", "timestamp_scale", "date_format", "safe_timestamp_numeric")
        )

    def test_column_path_rotation(self):
        self._run_generated(
            9, ("timestamp_column", "date_column_format", "time_column_format", "timestamp_format")
        )

    def test_date_timestamp_interleave(self):
        self._run_generated(
            0, ("date_numeric", "timestamp_unix", "date_format", "safe_timestamp_format")
        )

    def test_time_timestamp_interleave(self):
        self._run_generated(
            1, ("time_cast", "timestamp_scale", "time_format", "timestamp_column")
        )

    def test_all_path_scramble(self):
        self._run_generated(
            3,
            (
                "date_cast",
                "safe_date_cast",
                "time_cast",
                "timestamp_unix",
                "timestamp_scale",
                "timestamp_format",
                "safe_timestamp_format",
                "date_format",
                "time_format",
                "date_numeric",
                "safe_timestamp_numeric",
                "timestamp_column",
                "date_column_format",
                "time_column_format",
            ),
        )
