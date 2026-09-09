import unittest

from sqlglot import exp, planner
from sqlglot.executor.python import PythonExecutor
from sqlglot.executor.table import ensure_tables


class _Plan:
    def __init__(self, leaves, root):
        self.leaves = leaves
        self.root = root


class TestPythonExecuteExceptions(unittest.TestCase):
    def _expect_failures(self, attempts, builder):
        failed = 0
        for index in range(attempts):
            executor, plan = builder(index)
            try:
                executor.execute(plan)
            except Exception:
                failed += 1
        self.assertEqual(failed, attempts)

    def _static_scan(self, expression, suffix):
        step = planner.Scan()
        step.name = f"static_{suffix}"
        step.projections = [exp.alias_(expression, f"value_{suffix}")]
        return PythonExecutor(), _Plan((step,), step)

    def _late_scan(self, expression, depth, suffix):
        first = planner.Scan()
        first.name = f"stage_{suffix}_0"
        first.projections = [exp.alias_(exp.Literal.number(suffix + 1), "value")]
        previous = first

        for index in range(1, depth):
            step = planner.Scan()
            step.name = f"stage_{suffix}_{index}"
            step.source = exp.to_table(previous.name)
            step.add_dependency(previous)
            previous = step

        failing = planner.Scan()
        failing.name = f"stage_{suffix}_end"
        failing.source = exp.to_table(previous.name)
        if isinstance(expression, exp.Column) and not expression.table:
            expression = exp.column(expression.name, previous.name)
        failing.projections = [exp.alias_(expression, "result")]
        failing.add_dependency(previous)
        return PythonExecutor(), _Plan((first,), failing)

    def _table_scan(self, values, projection, suffix):
        source = f"source_{suffix}"
        step = planner.Scan()
        step.name = f"output_{suffix}"
        step.source = exp.to_table(source)
        step.projections = [exp.alias_(projection(source), "result")]
        tables = ensure_tables({source: [{"value": value} for value in values]})
        return PythonExecutor(tables=tables), _Plan((step,), step)

    def test_safe_long_dependency_chain(self):
        executor, plan = self._late_scan(
            exp.column("value"),
            ord("r") - ord("a"),
            ord("g") - ord("a"),
        )
        result = executor.execute(plan)
        self.assertEqual(len(result), len(plan.leaves))

    def test_safe_callee_handles_bad_values(self):
        def recover(value):
            try:
                return int(value)
            except Exception:
                return len(value)

        values = [
            f"bad_{index}_{index * index}"
            for index in range(ord("w") - ord("a"))
        ]
        source = "recover_source"
        step = planner.Scan()
        step.name = "recovered"
        step.source = exp.to_table(source)
        step.projections = [
            exp.alias_(exp.func("RECOVER", exp.column("value", source)), "result")
        ]
        executor = PythonExecutor(
            env={"RECOVER": recover},
            tables=ensure_tables({source: [{"value": value} for value in values]}),
        )
        result = executor.execute(_Plan((step,), step))
        self.assertEqual(len(result), len(values))
        self.assertTrue(all(row[0] for row in result.rows))

    def test_direct_arithmetic_failures(self):
        attempts = ord("f") - ord("a")
        self._expect_failures(
            attempts,
            lambda index: self._static_scan(
                exp.Literal.number(index + 1) / exp.Literal.number(index - index),
                index,
            ),
        )

    def test_late_arithmetic_failures(self):
        attempts = ord("d") - ord("a")
        self._expect_failures(
            attempts,
            lambda index: self._late_scan(
                exp.Literal.number(index + 2) / exp.Literal.number(index - index),
                ord("q") - ord("a") + index,
                index,
            ),
        )

    def test_missing_projection_columns(self):
        attempts = ord("h") - ord("a")
        values = [index * index + 1 for index in range(ord("t") - ord("a"))]
        self._expect_failures(
            attempts,
            lambda index: self._table_scan(
                values,
                lambda source: exp.column(f"absent_{index}", source),
                index,
            ),
        )

    def test_dependencies_not_scheduled(self):
        def build(index):
            omitted = planner.Scan()
            omitted.name = f"omitted_{index}"
            node = planner.Scan()
            node.name = f"dependent_{index}"
            node.source = exp.to_table(omitted.name)
            node.add_dependency(omitted)
            return PythonExecutor(), _Plan((node,), node)

        self._expect_failures(ord("e") - ord("a"), build)

    def test_root_not_in_executed_graph(self):
        def build(index):
            leaf = planner.Scan()
            leaf.name = f"leaf_{index}"
            root = planner.Scan()
            root.name = f"root_{index}"
            return PythonExecutor(), _Plan((leaf,), root)

        self._expect_failures(ord("c") - ord("a"), build)

    def test_unsupported_step_subclasses(self):
        def build(index):
            node = planner.Step()
            node.name = f"unsupported_{index}"
            return PythonExecutor(), _Plan((node,), node)

        self._expect_failures(ord("c") - ord("a"), build)

    def test_unknown_generated_functions(self):
        self._expect_failures(
            ord("g") - ord("a"),
            lambda index: self._static_scan(
                exp.func(f"UNKNOWN_{index}", exp.Literal.number(index)),
                index,
            ),
        )

    def test_distinct_union_with_nested_values(self):
        def build(index):
            left_name = f"left_{index}"
            right_name = f"right_{index}"
            values = [([index, offset],) for offset in range(ord("p") - ord("a"))]
            tables = ensure_tables(
                {
                    left_name: [{"value": value[0]} for value in values],
                    right_name: [{"value": value[0]} for value in reversed(values)],
                }
            )
            left = planner.Scan()
            left.name = left_name
            left.source = exp.to_table(left_name)
            right = planner.Scan()
            right.name = right_name
            right.source = exp.to_table(right_name)
            root = planner.SetOperation(exp.Union, left_name, right_name, distinct=True)
            root.name = f"union_{index}"
            root.add_dependency(left)
            root.add_dependency(right)
            return PythonExecutor(tables=tables), _Plan((left, right), root)

        self._expect_failures(ord("e") - ord("a"), build)

    def test_sort_with_incomparable_generated_values(self):
        def build(index):
            source = f"mixed_{index}"
            values = [
                offset if (offset + index) % 2 else f"text_{offset}"
                for offset in range(ord("u") - ord("a"))
            ]
            scan = planner.Scan()
            scan.name = source
            scan.source = exp.to_table(source)
            root = planner.Sort()
            root.name = f"sorted_{index}"
            root.key = [exp.Ordered(this=exp.column("value", source))]
            root.projections = [exp.column("value", source)]
            root.add_dependency(scan)
            tables = ensure_tables({source: [{"value": value} for value in values]})
            return PythonExecutor(tables=tables), _Plan((scan,), root)

        self._expect_failures(ord("d") - ord("a"), build)

    def test_aggregate_over_generated_text(self):
        def build(index):
            source = f"text_source_{index}"
            values = [
                f"part_{offset}_{index}"
                for offset in range(ord("s") - ord("a"))
            ]
            scan = planner.Scan()
            scan.name = source
            scan.source = exp.to_table(source)
            root = planner.Aggregate()
            root.name = f"aggregate_{index}"
            root.source = source
            root.aggregations = [
                exp.alias_(exp.Sum(this=exp.column("value", source)), "total")
            ]
            root.add_dependency(scan)
            tables = ensure_tables({source: [{"value": value} for value in values]})
            return PythonExecutor(tables=tables), _Plan((scan,), root)

        self._expect_failures(ord("c") - ord("a"), build)

    def test_malformed_set_operation_handler_interplay(self):
        def build(index):
            left_name = f"malformed_left_{index}"
            right_name = f"malformed_right_{index}"
            tables = ensure_tables(
                {
                    left_name: [{"value": index}],
                    right_name: [{"value": index + 1}],
                }
            )
            left = planner.Scan()
            left.name = left_name
            left.source = exp.to_table(left_name)
            right = planner.Scan()
            right.name = right_name
            right.source = exp.to_table(right_name)
            root = planner.SetOperation(exp.Literal.number(index), left_name, right_name)
            root.add_dependency(left)
            root.add_dependency(right)
            return PythonExecutor(tables=tables), _Plan((left, right), root)

        self._expect_failures(ord("f") - ord("a"), build)

    def test_malformed_aggregate_and_join_nodes(self):
        def aggregate(index):
            node = planner.Aggregate()
            node.name = f"bad_aggregate_{index}"
            node.group = None
            return PythonExecutor(), _Plan((node,), node)

        def join(index):
            node = planner.Join()
            node.name = f"bad_join_{index}"
            node.source_name = node.name
            node.joins = None
            dependency = planner.Scan()
            dependency.name = node.name
            node.add_dependency(dependency)
            return PythonExecutor(), _Plan((dependency,), node)

        self._expect_failures(ord("e") - ord("a"), aggregate)
        self._expect_failures(ord("d") - ord("a"), join)
