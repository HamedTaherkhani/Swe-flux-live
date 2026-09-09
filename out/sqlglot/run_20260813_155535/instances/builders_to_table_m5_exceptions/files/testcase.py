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
            f"catalog_{index}.schema_{index % 5}.table_{index * 3}"
            for index in range(ord("v") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "safe")

    def test_computed_empty_names(self):
        values = [f"discard_{index}"[:0] for index in range(ord("n") - ord("a"))]
        self._exercise(values, normalize_table_name, "failing")

    def test_trailing_separators(self):
        values = [
            f"tenant_{index}.segment_{index % 4}."
            for index in range(ord("r") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_separator_only_paths(self):
        values = [
            "." * (1 + index % 2)
            for index in range(ord("j") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_unclosed_delimited_identifiers(self):
        values = [
            '"' + f"table_{index}_{index * index}"
            for index in range(ord("h") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_unclosed_string_tokens(self):
        values = [
            "'" + f"table_{index}_{index + 3}"
            for index in range(ord("l") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_non_text_numeric_paths(self):
        values = [index * 7 + 1 for index in range(ord("f") - ord("a"))]
        self._exercise(values, normalize_table_name, "failing")

    def test_non_text_binary_paths(self):
        values = [
            f"binary_{index}".encode()
            for index in range(ord("i") - ord("a"))
        ]
        self._exercise(values, normalize_table_name, "failing")

    def test_rename_valid_source_invalid_destination(self):
        values = [
            (f"archive_{index}.source", f"archive_{index}.destination.")
            for index in range(ord("j") - ord("a"))
        ]
        self._exercise(values, lambda pair: rename_table(*pair), "failing")

    def test_rename_invalid_source_short_circuit(self):
        values = [
            ('"' + f"source_{index}", f"destination_{index}")
            for index in range(ord("g") - ord("a"))
        ]
        self._exercise(values, lambda pair: rename_table(*pair), "failing")

    def test_rename_columns_with_mixed_table_inputs(self):
        values = [
            f"warehouse_{index}.events" if index % 3 else index
            for index in range(ord("p") - ord("a"))
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
                    f"SELECT * FROM source_{index} JOIN side_{index} USING (id)"
                ),
                {
                    f"source_{index}": f"target_{index}",
                    f"side_{index}": f"dimension_{index}",
                },
            )
            for index in range(ord("m") - ord("a"))
        ]
        self._exercise(values, lambda pair: replace_tables(pair[0], pair[1]), "safe")

    def test_replace_with_unclosed_destinations(self):
        values = [
            (
                sqlglot.parse_one(f"SELECT * FROM source_{index}"),
                {f"source_{index}": '"' + f"target_{index}"},
            )
            for index in range(ord("k") - ord("a"))
        ]
        self._exercise(values, lambda pair: replace_tables(pair[0], pair[1]), "failing")

    def test_table_expression_inputs(self):
        values = [
            exp.Table(this=exp.to_identifier(f"table_{index}"))
            for index in range(ord("q") - ord("a"))
        ]
        self._exercise(
            values,
            lambda table: rename_column(table, "before", "after"),
            "safe",
        )
