import random
import unittest

from jinja2 import DictLoader, Environment
from jinja2.debug import rewrite_traceback_stack


def _build_include_chain(depth: int) -> dict[str, str]:
    templates: dict[str, str] = {}
    for index in range(depth):
        name = f"t{index}"
        if index == depth - 1:
            templates[name] = "{% set payload = boom() %}{{ payload }}"
        else:
            templates[name] = f"{{% include 't{index + 1}' %}}"
    templates["root"] = "{% include 't0' %}"
    return templates


def _make_boom(inner_depth: int):
    def boom():
        def inner(remaining: int):
            if remaining <= 0:
                return 1 / 0
            return inner(remaining - 1)

        return inner(inner_depth)

    return boom


class RewriteTracebackStackS3StateTest(unittest.TestCase):
    def test_direct_call_rewrites_nested_include_traceback(self) -> None:
        rng = random.Random(20260823)
        depth = 28 + rng.randint(0, 7)
        inner_depth = 14 + rng.randint(0, 6)

        env = Environment(loader=DictLoader(_build_include_chain(depth)))
        template = env.get_template("root")
        context = template.new_context({"boom": _make_boom(inner_depth)})

        rewritten = None
        try:
            env.concat(template.root_render_func(context))
        except Exception:
            rewritten = rewrite_traceback_stack()

        self.assertIsInstance(rewritten, ZeroDivisionError)
        self.assertIsNotNone(rewritten.__traceback__)

        frame_count = 0
        traceback = rewritten.__traceback__
        while traceback is not None:
            frame_count += 1
            traceback = traceback.tb_next

        self.assertGreater(frame_count, 10)
        self.assertGreaterEqual(inner_depth, 4)
