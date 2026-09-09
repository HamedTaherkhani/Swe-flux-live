import unittest

import sqlglot
from sqlglot import exp
from sqlglot.expressions import normalize_table_name, rename_column, rename_table, replace_tables


class TestToTableExceptions(unittest.TestCase):
    def _exercise(self, values, operation, expected):
        completed = 0
        failed = 0

        for value in values:
            try:
                result = operation(value)
                self.assertIsNotNone(result)
                completed += 1
            except Exception:
                failed += 1

        self.assertEqual(completed + failed, len(values))
        if expected == "safe":
            self.assertTrue(completed)
            self.assertFalse(failed)
        elif expected == "failing":
            self.assertFalse(completed)
            self.assertTrue(failed)
        else:
            self.assertTrue(completed)
            self.assertTrue(failed)

    def test_generated_qualified_names(self):
        values = [
            (
                f"table_{index}-name_{index % 4}"
                if index % 5 == 3
                else f"schema_{index % 4}$table_{index * 3}"
                if index % 5 == 1
                else f"single_table_{index}_{index * index}"
                if index % 5 == 2
                else f"catalog_{index}.schema_{index % 7}.table_{index * 5}"
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "safe")

    def test_computed_empty_names(self):
        values = [
            (
                f"discard_{index}_{index * 2}"[:0]
                if index % 3 != 1
                else f"void_{index}_{index % 5}"[: index % 1]
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_trailing_separators(self):
        values = [
            (
                f"tenant_{index}.segment_{index % 6}."
                if index % 3 != 1
                else f"zone_{index}.area_{index % 5}.."
                if index % 3 == 1
                else f"region_{index}."
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_separator_only_paths(self):
        values = [
            "." * (1 + index % 4) if index % 2 == 0 else ".." + "." * (index % 3)
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_unclosed_delimited_identifiers(self):
        values = [
            (
                '"' + f"table_{index}_{index * index}"
                if index % 3 != 2
                else '"' + f"source_{index}_{index + 5}_{index % 4}"
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_unclosed_string_tokens(self):
        values = [
            (
                "'" + f"table_{index}_{index + 3}"
                if index % 4 != 1
                else "'" + f"token_{index}_{index * 2}_suffix"
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_non_text_numeric_paths(self):
        values = [
            index * 11 + (index % 5) if index % 3 else index * -3 - 1
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_non_text_binary_paths(self):
        values = [
            (
                f"binary_{index}_{index % 4}".encode()
                if index % 2 == 0
                else bytes(f"raw_{index}", "utf-8")
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_rename_valid_source_invalid_destination(self):
        values = [
            (
                f"archive_{index}.source_{index % 4}",
                (
                    f"archive_{index}.destination_{index}."
                    if index % 3 != 2
                    else f"target_{index}.."
                ),
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, lambda pair: rename_table(*pair), "failing")

    def test_rename_invalid_source_short_circuit(self):
        values = [
            (
                (
                    '"' + f"source_{index}_{index % 3}"
                    if index % 2 == 0
                    else "'" + f"source_{index}_{index + 1}"
                ),
                f"destination_{index}_{index % 5}",
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, lambda pair: rename_table(*pair), "failing")

    def test_rename_columns_with_mixed_table_inputs(self):
        values = [
            (
                f"warehouse_{index}.events_{index % 6}"
                if index % 5 not in (0, 2)
                else index * 7 + 2
                if index % 5 == 0
                else f"broken_{index}."
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(
            values,
            lambda table: rename_column(table, "old_metric", "new_metric"),
            "mixed",
        )

    def test_replace_many_valid_tables(self):
        values = [
            (
                sqlglot.parse_one(
                    (
                        f"SELECT * FROM source_{index} JOIN side_{index % 5} USING (id)"
                        if index % 4 != 3
                        else f"SELECT * FROM source_{index} LEFT JOIN dim_{index} ON source_{index}.id = dim_{index}.id"
                    )
                ),
                {
                    f"source_{index}": (
                        f"target_{index}-schema_{index % 3}"
                        if index % 4 in (0, 2)
                        else f"mapped_{index}.layer_{index % 2}"
                    ),
                    f"side_{index % 5}": f"dimension_{index}_{index % 4}",
                    **(
                        {f"dim_{index}": f"layer_{index}$zone_{index % 2}"}
                        if index % 4 == 3
                        else {}
                    ),
                },
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, lambda pair: replace_tables(pair[0], pair[1]), "safe")

    def test_replace_with_unclosed_destinations(self):
        values = [
            (
                sqlglot.parse_one(
                    f"SELECT * FROM source_{index} WHERE source_{index}.id > {index % 7}"
                ),
                {
                    f"source_{index}": (
                        '"' + f"target_{index}_{index % 4}"
                        if index % 3 != 1
                        else "'" + f"target_{index}_{index + 2}"
                    )
                },
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(values, lambda pair: replace_tables(pair[0], pair[1]), "failing")

    def test_table_expression_inputs(self):
        values = [
            exp.Table(
                this=exp.to_identifier(f"table_{index}"),
                db=exp.to_identifier(f"schema_{index % 5}") if index % 4 in (1, 2) else None,
                catalog=exp.to_identifier(f"catalog_{index % 3}") if index % 6 == 0 else None,
            )
            for index in range(ord("z") - ord("a") + ord("f") - ord("a"))
        ]
        self._exercise(
            values,
            lambda table: rename_column(table, "before", "after"),
            "safe",
        )