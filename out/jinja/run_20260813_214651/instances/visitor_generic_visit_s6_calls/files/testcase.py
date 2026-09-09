import random
import unittest

from jinja2 import Environment
from jinja2 import nodes
from jinja2.visitor import NodeTransformer


def _build_source(seed: int) -> str:
    rng = random.Random(seed)
    lines: list[str] = []
    block_count = 12 + rng.randint(0, 8)
    for block in range(block_count):
        inner = 2 + (block % 5)
        lines.append(f"{{% for idx in range({inner}) %}}")
        lines.append(f"{{% set acc{block} = idx + {block} %}}")
        if block % 3 == 0:
            lines.append(f"{{% if acc{block} > {block + 1} %}}")
            lines.append(f"{{{{ acc{block} }}}}")
            lines.append("{% else %}")
            lines.append(f"{{{{ acc{block} + 1 }}}}")
            lines.append("{% endif %}")
        elif block % 3 == 1:
            lines.append(f"{{{{ acc{block} * 2 }}}}")
        else:
            lines.append(f"{{{{ acc{block} - 1 }}}}")
        lines.append("{% endfor %}")
    return "\n".join(lines)


class _ListFanoutTransformer(NodeTransformer):
    def visit_Assign(self, node: nodes.Assign, *args, **kwargs):
        target = node.target
        if isinstance(target, nodes.Name) and target.name.startswith("acc"):
            return [node, nodes.Output([nodes.Const(0)])]
        return node

    def visit_Output(self, node: nodes.Output, *args, **kwargs):
        expanded: list[nodes.Node] = []
        for child in node.nodes:
            expanded.append(child)
            if isinstance(child, nodes.Name):
                expanded.append(nodes.Const(1))
        return nodes.Output(expanded)

    def visit_If(self, node: nodes.If, *args, **kwargs):
        if node.test.lineno % 2 == 0:
            return None
        return node


def _run_transform_via_visit_list(
    transformer: NodeTransformer, root: nodes.Template,
) -> list[nodes.Node]:
    return transformer.visit_list(root)


class TestGenericVisitCallOrder(unittest.TestCase):
    def test_visit_list_transform(self) -> None:
        env = Environment()
        source = _build_source(20240814)
        ast = env.parse(source)
        transformer = _ListFanoutTransformer()
        result = _run_transform_via_visit_list(transformer, ast)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        body = result[0].body
        self.assertGreater(len(body), 20)
        checksum = sum(stmt.lineno or 0 for stmt in body)
        self.assertGreater(checksum, 0)
        self.assertGreater(sum(1 for stmt in body if stmt.lineno is not None), 15)
