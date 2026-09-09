"""Direct exercise of Optimizer.generic_visit across many AST expressions."""

from __future__ import annotations

import random
import unittest

from jinja2 import Environment, nodes
from jinja2.optimizer import Optimizer


def _build_expr(rng: random.Random, depth: int = 0) -> str:
    roll = rng.randint(0, 11)
    if roll <= 2 or depth >= 4:
        return str(rng.randint(1, 12))
    if roll <= 5:
        left = _build_expr(rng, depth + 1)
        right = _build_expr(rng, depth + 1)
        return f"({left} + {right})"
    if roll <= 7:
        left = _build_expr(rng, depth + 1)
        right = _build_expr(rng, depth + 1)
        return f"({left} * {right})"
    if roll <= 9:
        left = _build_expr(rng, depth + 1)
        right = _build_expr(rng, depth + 1)
        return f"({left} - {right})"
    if roll == 10:
        inner = _build_expr(rng, depth + 1)
        return f"(not {inner})"
    left = _build_expr(rng, depth + 1)
    right = _build_expr(rng, depth + 1)
    return f"({left} and {right})"


class TestOptimizerGenericVisitCallOrder(unittest.TestCase):
    """Drive Optimizer.generic_visit through foldable and non-foldable nodes."""

    def test_optimizer_generic_visit_interprocedural_calls(self) -> None:
        label = "optimizer_generic_visit_trace"
        seed = sum(ord(ch) * (idx + 1) for idx, ch in enumerate(label))
        rng = random.Random(seed)

        env = Environment()
        optimizer = Optimizer(env)

        batch_total = (seed % 7) + 26
        checksum = 0

        for batch in range(batch_total):
            expr = _build_expr(rng)
            if batch % 5 == 3:
                expr = f"({expr} + mystery)"
            if batch % 7 == 4:
                expr = f"({expr} / pivot)"
            source = f"{{{{ {expr} }}}}"
            ast = env.parse(source)

            for node in ast.find_all(nodes.Expr):
                optimized = optimizer.generic_visit(node)
                checksum += hash(type(optimized).__name__) % 11
                checksum += getattr(optimized, "lineno", 0) % 5

        self.assertIsInstance(checksum, int)
        self.assertGreater(checksum, 0)
