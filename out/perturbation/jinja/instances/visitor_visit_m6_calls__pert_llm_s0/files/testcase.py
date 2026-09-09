import random
import unittest

from jinja2 import Environment
from jinja2 import nodes
from jinja2.visitor import NodeTransformer
from jinja2.visitor import NodeVisitor


def _stable_mix(values: list[int]) -> int:
    total = 0
    for index, value in enumerate(values):
        total ^= (value * (index + 5)) % 10009
    return total % 9973


def _build_source(seed: int) -> str:
    rng = random.Random(seed)
    lines: list[str] = []
    block_count = 14 + rng.randint(0, 6)
    for block in range(block_count):
        inner = 2 + (block % 7)
        lines.append(f"{{% for idx in range({inner}) %}}")
        lines.append(f"{{% set acc{block} = idx + {block} %}}")
        if block % 4 == 0:
            lines.append(f"{{% if acc{block} > {block + 1} %}}")
            lines.append(f"{{{{ acc{block} }}}}")
            lines.append("{% else %}")
            lines.append(f"{{{{ acc{block} + 1 }}}}")
            lines.append("{% endif %}")
        elif block % 4 == 1:
            lines.append(f"{{{{ acc{block} * 2 }}}}")
        elif block % 4 == 2:
            lines.append(f"{{% if idx % 2 == 0 %}}{{{{ acc{block} }}}}{{% endif %}}")
        else:
            lines.append(f"{{{{ acc{block} - 1 }}}}")
        lines.append("{% endfor %}")
    return "\n".join(lines)


def _parse_template(seed: int) -> nodes.Template:
    env = Environment()
    return env.parse(_build_source(seed))


class _ConstOnlyVisitor(NodeVisitor):
    def visit_Const(self, node: nodes.Const, *args, **kwargs):
        return node


class _OutputExpandVisitor(NodeVisitor):
    def visit_Output(self, node: nodes.Output, *args, **kwargs):
        expanded: list[nodes.Node] = []
        for child in node.nodes:
            expanded.append(child)
            if isinstance(child, nodes.Name):
                expanded.append(nodes.Const(0))
        return nodes.Output(expanded)


class _PruneIfTransformer(NodeTransformer):
    def visit_If(self, node: nodes.If, *args, **kwargs):
        if node.test.lineno % 3 == 0:
            return None
        return node


class _AssignFanoutTransformer(NodeTransformer):
    def visit_Assign(self, node: nodes.Assign, *args, **kwargs):
        target = node.target
        if isinstance(target, nodes.Name) and target.name.startswith("acc"):
            return [node, nodes.Output([nodes.Const(0)])]
        return node


class _NameStripTransformer(NodeTransformer):
    def visit_Name(self, node: nodes.Name, *args, **kwargs):
        if len(node.name) % 2 == 0:
            return None
        return node


class TestVisitInvocationCounts(unittest.TestCase):
    def test_plain_visitor_on_parsed_root(self) -> None:
        root = _parse_template(73001)
        visitor = NodeVisitor()
        visitor.visit(root)
        self.assertGreater(len(root.body), 18)
        self.assertGreater(_stable_mix([stmt.lineno or 0 for stmt in root.body]), 0)

    def test_const_handler_short_circuit(self) -> None:
        root = _parse_template(73002)
        visitor = _ConstOnlyVisitor()
        visitor.visit(root)
        const_nodes = [n for n in root.find_all(nodes.Const)]
        self.assertGreater(len(const_nodes), 8)

    def test_output_expand_handler(self) -> None:
        root = _parse_template(73003)
        visitor = _OutputExpandVisitor()
        visitor.visit(root)
        outputs = list(root.find_all(nodes.Output))
        self.assertGreater(len(outputs), 12)

    def test_transformer_prune_if(self) -> None:
        root = _parse_template(73004)
        transformer = _PruneIfTransformer()
        transformer.visit(root)
        remaining_ifs = list(root.find_all(nodes.If))
        self.assertGreater(len(remaining_ifs), 0)
        self.assertLess(len(remaining_ifs), 40)

    def test_transformer_assign_fanout(self) -> None:
        root = _parse_template(73005)
        transformer = _AssignFanoutTransformer()
        transformer.visit(root)
        assigns = list(root.find_all(nodes.Assign))
        self.assertGreater(len(assigns), 10)

    def test_transformer_name_strip(self) -> None:
        root = _parse_template(73006)
        transformer = _NameStripTransformer()
        transformer.visit(root)
        names = list(root.find_all(nodes.Name))
        self.assertGreater(len(names), 5)

    def test_batched_leaf_const_visits(self) -> None:
        visitor = NodeVisitor()
        rng = random.Random(73007)
        checksum = 0
        for index in range(63):
            value = rng.randint(3, 127) + index * 2
            checksum ^= value
            visitor.visit(nodes.Const(value))
        self.assertGreater(checksum, 0)

    def test_sequential_parsed_templates(self) -> None:
        visitor = NodeVisitor()
        widths: list[int] = []
        for offset in range(19):
            root = _parse_template(73008 + offset)
            visitor.visit(root)
            widths.append(len(root.body))
        self.assertGreater(sum(widths), 90)

    def test_mixed_handlers_on_smaller_tree(self) -> None:
        env = Environment()
        source = (
            "{% for x in range(13) %}"
            "{% if x % 4 == 0 %}{{ x }}{% elif x % 4 == 1 %}{{ x * 3 }}"
            "{% elif x % 4 == 2 %}{{ x - 1 }}{% else %}{{ x + 2 }}{% endif %}"
            "{% endfor %}"
        )
        root = env.parse(source)
        visitor = _OutputExpandVisitor()
        visitor.visit(root)
        self.assertGreater(len(list(root.find_all(nodes.For))), 0)

    def test_transformer_on_macro_template(self) -> None:
        env = Environment()
        source = (
            "{% macro item(n, m, p) %}{{ n + m + p }}{% endmacro %}"
            "{% for k in range(19) %}{{ item(k, k % 5, k // 3) }}{% endfor %}"
        )
        root = env.parse(source)
        transformer = _PruneIfTransformer()
        transformer.visit(root)
        self.assertIsNotNone(root.find(nodes.Macro))

    def test_deep_binop_chain(self) -> None:
        env = Environment()
        expr = "3"
        for step in range(41):
            expr = f"({expr} + {step + 4})"
        root = env.parse(f"{{{{ {expr} }}}}")
        visitor = NodeVisitor()
        visitor.visit(root)
        binops = list(root.find_all(nodes.BinExpr))
        self.assertGreater(len(binops), 12)

    def test_filter_heavy_template(self) -> None:
        env = Environment()
        parts = []
        for idx in range(37):
            parts.append(f"{{{{ 'variant{idx}'|upper|length|default({idx}) }}}}")
        root = env.parse("\n".join(parts))
        visitor = _ConstOnlyVisitor()
        visitor.visit(root)
        filters = list(root.find_all(nodes.Filter))
        self.assertGreater(len(filters), 10)

    def test_transformer_nested_for_blocks(self) -> None:
        env = Environment()
        lines = ["{% for outer in range(9) %}"]
        for inner in range(13):
            lines.append(
                f"{{% for inner{inner} in range(6) %}}{{{{ outer + inner{inner} }}}}{{% endfor %}}"
            )
        lines.append("{% endfor %}")
        root = env.parse("\n".join(lines))
        transformer = _AssignFanoutTransformer()
        transformer.visit(root)
        fors = list(root.find_all(nodes.For))
        self.assertGreater(len(fors), 4)
