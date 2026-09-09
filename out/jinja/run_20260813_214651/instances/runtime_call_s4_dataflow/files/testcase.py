"""Exercise Context.call def-use dynamics across many invocations."""

from __future__ import annotations

import unittest

from jinja2 import Environment
from jinja2.runtime import new_context
from jinja2.utils import pass_context, pass_eval_context, pass_environment


@pass_context
def _ctx_scale(context, base: int, factor: int) -> int:
    return base * factor + len(context.vars)


@pass_eval_context
def _eval_flag(eval_ctx, bit: int) -> int:
    return int(eval_ctx.autoescape) + bit


@pass_environment
def _env_shift(environment, offset: int) -> int:
    return offset + len(environment.globals)


class _CtxCallable:
    @pass_context
    def __call__(self, context, value: int) -> int:
        return value + len(context.parent)


def _plain_sum(*values: int, tag: int = 0) -> int:
    return sum(values) + tag


def _stop_now() -> int:
    raise StopIteration()


class TestContextCallDataFlow(unittest.TestCase):
    """Drive Context.call through pass-arg and exception branches."""

    def test_context_call_def_use_dataflow(self) -> None:
        label = "ctx_call_trace"
        seed = sum(ord(ch) * (idx + 1) for idx, ch in enumerate(label))

        env = Environment()
        ctx = new_context(env, "probe", {}, {})

        total = (seed % 9) + 20
        acc = 0

        for step in range(total):
            phase = (seed + step * 5) % 9
            base = (seed + step) % 17
            factor = (step % 5) + 1
            loop_payload = {f"k{step % 4}": base + step}
            block_payload = {f"b{step % 3}": factor + step}

            if phase == 0:
                acc += ctx.call(_plain_sum, base, factor, tag=step % 3)
            elif phase == 1:
                acc += ctx.call(_ctx_scale, base, factor)
            elif phase == 2:
                acc += ctx.call(
                    _ctx_scale,
                    base,
                    factor,
                    _loop_vars=loop_payload,
                )
            elif phase == 3:
                acc += ctx.call(
                    _ctx_scale,
                    base,
                    factor,
                    _block_vars=block_payload,
                )
            elif phase == 4:
                acc += ctx.call(
                    _ctx_scale,
                    base,
                    factor,
                    _loop_vars=loop_payload,
                    _block_vars=block_payload,
                )
            elif phase == 5:
                acc += ctx.call(_eval_flag, step % 2)
            elif phase == 6:
                acc += ctx.call(_env_shift, base)
            elif phase == 7:
                acc += ctx.call(_CtxCallable(), base)
            else:
                ctx.call(_stop_now)
                acc += step % 4

        self.assertIsInstance(acc, int)
        self.assertGreater(acc, 0)
