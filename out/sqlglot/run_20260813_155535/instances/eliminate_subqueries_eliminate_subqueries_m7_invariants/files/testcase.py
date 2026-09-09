import unittest

from sqlglot import exp, parse_one
from sqlglot.optimizer.eliminate_subqueries import eliminate_subqueries


def _derived_join_query(width, salt, duplicate_period=None):
    pieces = []
    for index in range(width):
        value = index if duplicate_period is None else index % duplicate_period
        projected = (value * value + salt * (index + 1)) % (width + salt + 7)
        pieces.append(
            f"(SELECT {value + salt} AS k, {projected} AS v FROM base_{value % 5}) AS d{index}"
        )
    return "SELECT * FROM " + " CROSS JOIN ".join(pieces)


def _nested_query(depth, salt):
    query = f"SELECT {salt} AS seed FROM source_{salt % 4}"
    for index in range(depth):
        query = (
            f"SELECT n{index}.seed, {salt + index} AS layer "
            f"FROM ({query}) AS n{index}"
        )
    return query


class TestEliminateSubqueriesInvariants(unittest.TestCase):
    def test_distinct_derived_join_fanout(self):
        expression = parse_one(_derived_join_query(sum(range(1, 6)), 3))
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsInstance(result, exp.Query)
        self.assertTrue(result.sql())

    def test_periodic_duplicate_fanout(self):
        width = len([value for value in range(30) if value % 2])
        expression = parse_one(_derived_join_query(width, 5, duplicate_period=4))
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsNotNone(result.args.get("with_"))

    def test_deep_nested_chain(self):
        depth = sum(value % 3 for value in range(17))
        expression = parse_one(_nested_query(depth, 7))
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIn("WITH", result.sql())

    def test_union_of_generated_branches(self):
        branches = [
            f"SELECT * FROM (SELECT {index * index + 2} AS x FROM u_{index % 3}) AS b{index}"
            for index in range(13)
        ]
        expression = parse_one(" UNION ALL ".join(branches))
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertGreater(len(list(result.walk())), len(branches))

    def test_existing_ctes_with_nested_sources(self):
        ctes = []
        for index in range(7):
            inner = _nested_query(index % 4 + 2, index + 11)
            ctes.append(f"w{index} AS (SELECT * FROM ({inner}) AS z{index})")
        expression = parse_one(
            f"WITH {', '.join(ctes)} SELECT * FROM "
            + " CROSS JOIN ".join(f"w{index}" for index in range(len(ctes)))
        )
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsInstance(result.args.get("with_"), exp.With)

    def test_insert_select_source(self):
        width = sum(1 for value in range(40) if value % 3 == 1)
        select = _derived_join_query(width, 13, duplicate_period=5)
        expression = parse_one(f"INSERT INTO sink_table {select}")
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsInstance(result, exp.Insert)

    def test_create_table_as_select(self):
        depth = len({value * value % 19 for value in range(23)})
        expression = parse_one(f"CREATE TABLE made_table AS {_nested_query(depth, 17)}")
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsInstance(result, exp.Create)

    def test_parenthesized_root_subquery(self):
        width = len(tuple(range(3, 18, 2)))
        sql = f"({_derived_join_query(width, 19, duplicate_period=3)}) LIMIT {width % 5 + 1}"
        expression = parse_one(sql)
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertTrue(result.sql())

    def test_lateral_correlated_sources(self):
        terms = []
        for index in range(9):
            terms.append(
                f"LATERAL (SELECT p.k + {index + 1} AS q FROM aux_{index % 4}) AS l{index}"
            )
        expression = parse_one(
            "SELECT * FROM (SELECT 1 AS k) AS p CROSS JOIN " + " CROSS JOIN ".join(terms)
        )
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsInstance(result, exp.Query)

    def test_alias_and_table_name_collisions(self):
        aliases = [f"base_{index % 5}" for index in range(14)]
        sources = [
            f"(SELECT {index + 23} AS x FROM base_{(index + 1) % 5}) AS {alias}"
            for index, alias in enumerate(aliases)
        ]
        expression = parse_one("SELECT * FROM " + " CROSS JOIN ".join(sources))
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertIsNotNone(result.args.get("with_"))

    def test_mixed_unique_and_repeated_shapes(self):
        sources = []
        for index in range(16):
            token = (index * 7) % 6
            sources.append(
                f"(SELECT {token} AS a, {token * token} AS b FROM mix_{token % 2}) AS m{index}"
            )
        expression = parse_one("SELECT * FROM " + " CROSS JOIN ".join(sources))
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertTrue(any(isinstance(node, exp.CTE) for node in result.walk()))

    def test_recursive_cte_and_derived_tail(self):
        tail = _derived_join_query(len(range(2, 20, 2)), 29, duplicate_period=3)
        expression = parse_one(
            "WITH RECURSIVE nums AS ("
            "SELECT 1 AS n UNION ALL SELECT n + 1 FROM nums WHERE n < 4"
            f") SELECT * FROM nums CROSS JOIN ({tail}) AS tail"
        )
        result = eliminate_subqueries(expression)
        self.assertIs(result, expression)
        self.assertTrue(result.args["with_"].args.get("recursive"))
