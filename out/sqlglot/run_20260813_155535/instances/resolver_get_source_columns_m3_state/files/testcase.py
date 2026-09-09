import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.qualify import qualify


class TestResolverSourceColumnStates(unittest.TestCase):
    def qualify_query(self, sql, schema=None, dialect=None):
        result = qualify(
            parse_one(sql, read=dialect),
            schema=schema or {},
            dialect=dialect,
            quote_identifiers=False,
            validate_qualify_columns=False,
        )
        self.assertIsInstance(result, exp.Query)
        self.assertGreater(len(list(result.walk())), 4)
        return result

    def test_01_generated_tables_and_using_join(self):
        width = 17 + sum(index % 4 for index in range(6))
        columns = [f"metric_{index:02d}" for index in range(width)]
        schema = {
            table: {column: "INT" if index % 3 else "DOUBLE" for index, column in enumerate(columns)}
            for table in ("fact_left", "fact_right")
        }
        result = self.qualify_query(
            f"SELECT * FROM fact_left JOIN fact_right USING ({', '.join(columns[2:7:2])})",
            schema,
        )
        self.assertGreater(len(result.selects), width)

    def test_02_cte_column_alias_shadowing(self):
        width = 13 + sum(index % 5 for index in range(8))
        source_columns = [f"raw_{index:02d}" for index in range(width)]
        aliases = [f"clean_{(index * 7) % width:02d}" for index in range(width)]
        projections = ", ".join(source_columns)
        result = self.qualify_query(
            f"WITH staged({', '.join(aliases)}) AS "
            f"(SELECT {projections} FROM source_events) SELECT * FROM staged",
            {"source_events": {name: "INT" for name in source_columns}},
        )
        self.assertEqual(len(result.selects), width)

    def test_03_values_with_derived_aliases(self):
        width = 11 + sum(index % 4 for index in range(9))
        aliases = [f"value_{index * index + 3:03d}" for index in range(width)]
        row = ", ".join(str((index * 11 + 5) % 97) for index in range(width))
        result = self.qualify_query(
            f"SELECT * FROM (VALUES ({row}), ({row})) AS generated({', '.join(aliases)})"
        )
        self.assertEqual(len(result.selects), width)

    def test_04_nested_union_outputs(self):
        width = 12 + sum((index * index) % 5 for index in range(7))
        names = [f"union_{index:02d}_{(index * 13) % 29:02d}" for index in range(width)]
        left = ", ".join(f"{index + 1} AS {name}" for index, name in enumerate(names))
        right = ", ".join(str((index + 2) * 3) for index in range(width))
        result = self.qualify_query(
            f"WITH merged AS (SELECT {left} UNION ALL SELECT {right}) "
            "SELECT * FROM merged"
        )
        self.assertEqual(len(result.selects), width)

    def test_05_bigquery_literal_struct_unnest(self):
        width = 10 + sum(index % 3 for index in range(11))
        fields = [f"field_{index:02d}_{(index * 17) % 31:02d}" for index in range(width)]
        struct_items = ", ".join(
            f"{index * index + 1} AS {field}" for index, field in enumerate(fields)
        )
        result = self.qualify_query(
            f"SELECT item.* FROM UNNEST([STRUCT({struct_items})]) AS item",
            dialect="bigquery",
        )
        self.assertEqual(len(result.selects), width)

    def test_06_bigquery_typed_struct_unnest(self):
        width = 14 + sum((index + 1) % 4 for index in range(8))
        fields = [f"payload_{index:02d}_{(index * 19) % 37:02d}" for index in range(width)]
        struct_type = ", ".join(
            f"{field} {'STRING' if index % 2 else 'INT64'}"
            for index, field in enumerate(fields)
        )
        schema = {"event_stream": {"batch": f"ARRAY<STRUCT<{struct_type}>>"}}
        result = self.qualify_query(
            "SELECT entry.* FROM event_stream CROSS JOIN UNNEST(event_stream.batch) AS entry",
            schema,
            "bigquery",
        )
        self.assertEqual(len(result.selects), width)

    def test_07_spark_lateral_explode_struct(self):
        width = 9 + sum((index * 3) % 7 for index in range(10))
        fields = [f"attribute_{index:02d}_{(index * 23) % 41:02d}" for index in range(width)]
        struct_type = ", ".join(
            f"{field}: {'STRING' if index % 3 else 'INT'}"
            for index, field in enumerate(fields)
        )
        schema = {"catalog_items": {"records": f"ARRAY<STRUCT<{struct_type}>>"}}
        result = self.qualify_query(
            "SELECT exploded.* FROM catalog_items "
            "LATERAL VIEW EXPLODE(records) generated AS exploded",
            schema,
            "spark",
        )
        self.assertTrue(any(isinstance(node, exp.Lateral) for node in result.walk()))

    def test_08_nested_derived_table_aliases(self):
        width = 15 + sum(index % 6 for index in range(7))
        base = [f"base_{index:02d}" for index in range(width)]
        middle = [f"middle_{(index * 5 + 2) % (width + 3):02d}" for index in range(width)]
        outer = [f"outer_{(index * 9 + 1) % (width + 5):02d}" for index in range(width)]
        result = self.qualify_query(
            f"SELECT * FROM (SELECT * FROM "
            f"(SELECT {', '.join(base)} FROM deep_source) "
            f"AS inner_q({', '.join(middle)})) AS outer_q({', '.join(outer)})",
            {"deep_source": {name: "BIGINT" for name in base}},
        )
        self.assertEqual(len(result.selects), width)

    def test_09_snowflake_pivot_chain(self):
        category_count = 8 + sum(index % 4 for index in range(6))
        categories = [f"kind_{(index * 7 + 4) % 53:02d}" for index in range(category_count)]
        pivot_values = ", ".join(f"'{name}' AS p_{index:02d}" for index, name in enumerate(categories))
        schema = {
            "measurements": {
                "entity_id": "INT",
                "category": "VARCHAR",
                "reading": "DOUBLE",
                **{f"tag_{index:02d}": "VARCHAR" for index in range(category_count)},
            }
        }
        result = self.qualify_query(
            "SELECT * FROM measurements "
            f"PIVOT(SUM(reading) FOR category IN ({pivot_values}))",
            schema,
            "snowflake",
        )
        self.assertGreater(len(result.selects), category_count)

    def test_10_snowflake_unpivot_chain(self):
        width = 16 + sum(index % 5 for index in range(8))
        measures = [f"period_{index:02d}_{(index * 29) % 47:02d}" for index in range(width)]
        schema = {"wide_metrics": {"account_id": "INT", **{name: "DOUBLE" for name in measures}}}
        result = self.qualify_query(
            "SELECT * FROM wide_metrics "
            f"UNPIVOT(amount FOR period_name IN ({', '.join(measures)}))",
            schema,
            "snowflake",
        )
        self.assertGreaterEqual(len(result.selects), 3)

    def test_11_transform_query_schema(self):
        width = 10 + sum((index * 5) % 6 for index in range(9))
        inputs = [f"input_{index:02d}_{(index * 31) % 59:02d}" for index in range(width)]
        outputs = [f"output_{index:02d}_{(index * 37) % 61:02d}" for index in range(width)]
        schema_clause = ", ".join(
            f"{name} {'STRING' if index % 2 else 'INT'}"
            for index, name in enumerate(outputs)
        )
        result = self.qualify_query(
            f"SELECT TRANSFORM({', '.join(inputs)}) USING 'process' AS ({schema_clause}) "
            "FROM transform_source",
            {"transform_source": {name: "STRING" for name in inputs}},
            "spark",
        )
        self.assertEqual(len(result.selects), 1)

    def test_12_correlated_bigquery_unnests(self):
        width = 12 + sum((index * 2) % 7 for index in range(9))
        child_fields = [f"child_{index:02d}_{(index * 41) % 67:02d}" for index in range(width)]
        child_struct = ", ".join(
            f"{name} {'FLOAT64' if index % 2 else 'INT64'}"
            for index, name in enumerate(child_fields)
        )
        schema = {
            "parent_rows": {
                "row_id": "INT64",
                "children": f"ARRAY<STRUCT<{child_struct}>>",
            }
        }
        result = self.qualify_query(
            "SELECT row_id, (SELECT AS STRUCT child.* "
            "FROM UNNEST(parent_rows.children) AS child LIMIT 1) AS first_child "
            "FROM parent_rows",
            schema,
            "bigquery",
        )
        self.assertEqual(len(result.selects), 2)
