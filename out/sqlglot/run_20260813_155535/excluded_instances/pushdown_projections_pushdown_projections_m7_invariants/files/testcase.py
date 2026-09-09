import random
import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.pushdown_projections import pushdown_projections
from sqlglot.optimizer.qualify import qualify


class TestPushdownProjectionInvariants(unittest.TestCase):
    @staticmethod
    def _column_names(seed, width):
        numbers = list(range(width))
        random.Random(seed).shuffle(numbers)
        return [f"c{number}" for number in numbers]

    def _run(self, sql, tables, *, dialect=None, remove_unused_selections=True):
        width = 7 + 6
        schema = {
            table: {f"c{index}": "INT" for index in range(width)}
            for table in sorted(set(tables))
        }
        expression = qualify(
            parse_one(sql, dialect=dialect),
            schema=schema,
            dialect=dialect,
            identify=False,
            validate_qualify_columns=False,
        )
        result = pushdown_projections(
            expression,
            schema=schema,
            dialect=dialect,
            remove_unused_selections=remove_unused_selections,
        )
        self.assertIs(result, expression)
        self.assertIsInstance(result, exp.Expression)
        self.assertGreater(len(result.sql(dialect=dialect)), len(tables))

    def _nested_sql(self, seed, depth, width):
        columns = self._column_names(seed, width)
        table = f"base_{seed}"
        alias_name = f"b{seed % 7}"
        sql = f"SELECT {', '.join(f'{alias_name}.{column}' for column in columns)} FROM {table} AS {alias_name}"
        for level in range(depth):
            source_name = f"{'q' if level % 3 else 'layer'}{seed % 9}_{level}"
            kept = columns[: max(2, len(columns) - (level % 4))]
            sql = (
                f"SELECT {', '.join(f'{source_name}.{column}' for column in kept)} "
                f"FROM ({sql}) AS {source_name}"
            )
            columns = kept
        return sql, [table]

    def _nested_output_columns(self, seed, depth, width):
        columns = self._column_names(seed, width)
        for level in range(depth):
            columns = columns[: max(2, len(columns) - (level % 4))]
        return columns

    def test_deep_alternating_chain(self):
        sql, tables = self._nested_sql(31, 7, 9)
        self._run(sql, tables)

    def test_two_branches_join(self):
        left, left_tables = self._nested_sql(43, 4, 8)
        right, right_tables = self._nested_sql(59, 5, 8)
        left_columns = self._nested_output_columns(43, 4, 8)
        right_columns = self._nested_output_columns(59, 5, 8)
        sql = (
            f"SELECT qleft.{left_columns[0]}, branch.{right_columns[1]} "
            f"FROM ({left}) AS qleft "
            f"JOIN ({right}) AS branch "
            f"ON qleft.{left_columns[-1]} = branch.{right_columns[-1]}"
        )
        self._run(sql, left_tables + right_tables)

    def test_cte_pipeline(self):
        columns = self._column_names(83, 10)
        table = "events_cte"
        projections = ", ".join(f"e.{column}" for column in columns)
        sql = (
            f"WITH stage_one AS (SELECT {projections} FROM {table} AS e), "
            f"qstage AS (SELECT {', '.join(f'stage_one.{c}' for c in columns[:-2])} FROM stage_one), "
            f"final_stage AS (SELECT {', '.join(f'qstage.{c}' for c in columns[1:-3])} FROM qstage) "
            f"SELECT final_stage.{columns[2]} FROM final_stage"
        )
        self._run(sql, [table])

    def test_union_all_tree(self):
        left, left_tables = self._nested_sql(97, 3, 7)
        right, right_tables = self._nested_sql(101, 3, 7)
        columns = self._nested_output_columns(97, 3, 7)
        sql = (
            f"SELECT unioned.{columns[0]} FROM "
            f"(({left}) UNION ALL ({right})) AS unioned"
        )
        self._run(sql, left_tables + right_tables)

    def test_union_distinct_tree(self):
        left, left_tables = self._nested_sql(107, 4, 6)
        right, right_tables = self._nested_sql(109, 4, 6)
        columns = self._nested_output_columns(107, 4, 6)
        sql = f"SELECT qunion.{columns[-1]} FROM (({left}) UNION ({right})) AS qunion"
        self._run(sql, left_tables + right_tables)

    def test_intersect_all_tree(self):
        left, left_tables = self._nested_sql(127, 3, 5)
        right, right_tables = self._nested_sql(131, 3, 5)
        columns = self._column_names(137, 5)
        sql = (
            f"SELECT matched.{columns[1]} FROM "
            f"(({left}) INTERSECT ALL ({right})) AS matched"
        )
        self._run(sql, left_tables + right_tables)

    def test_distinct_and_ordered_layers(self):
        inner, tables = self._nested_sql(139, 5, 9)
        columns = self._nested_output_columns(139, 5, 9)
        sql = (
            f"SELECT DISTINCT qordered.{columns[0]}, qordered.{columns[1]} "
            f"FROM ({inner}) AS qordered ORDER BY {columns[1]}"
        )
        self._run(sql, tables)

    def test_grouped_aggregate_layer(self):
        columns = self._column_names(151, 8)
        table = "metrics_grouped"
        sql = (
            f"SELECT grouped.{columns[0]} FROM ("
            f"SELECT m.{columns[0]}, SUM(m.{columns[1]}) AS {columns[1]}, "
            f"MAX(m.{columns[2]}) AS {columns[2]} FROM {table} AS m "
            f"GROUP BY m.{columns[0]}"
            f") AS grouped"
        )
        self._run(sql, [table])

    def test_star_expansion_layers(self):
        table = "wide_star"
        columns = self._column_names(157, 11)
        sql = (
            f"SELECT qstar.{columns[0]} FROM ("
            f"SELECT star_layer.* FROM (SELECT * FROM {table}) AS star_layer"
            f") AS qstar"
        )
        self._run(sql, [table])

    def test_positional_alias_columns(self):
        columns = self._column_names(163, 6)
        table = "aliased_positions"
        aliases = [f"renamed_{index}" for index in range(3)]
        sql = (
            f"SELECT qalias.{aliases[1]} FROM ("
            f"SELECT p.{columns[0]}, p.{columns[1]}, p.{columns[2]} FROM {table} AS p"
            f") AS qalias ({', '.join(aliases)})"
        )
        self._run(sql, [table])

    def test_pruning_disabled(self):
        sql, tables = self._nested_sql(167, 8, 10)
        self._run(sql, tables, remove_unused_selections=False)

    def test_correlated_exists_layers(self):
        outer_columns = self._column_names(173, 7)
        inner_columns = self._column_names(179, 7)
        outer_table = "outer_records"
        inner_table = "inner_records"
        sql = (
            f"SELECT qouter.{outer_columns[0]} FROM ("
            f"SELECT o.{outer_columns[0]}, o.{outer_columns[1]} FROM {outer_table} AS o "
            f"WHERE EXISTS (SELECT i.{inner_columns[2]} FROM {inner_table} AS i "
            f"WHERE i.{inner_columns[1]} = o.{outer_columns[1]})"
            f") AS qouter"
        )
        self._run(sql, [outer_table, inner_table])
