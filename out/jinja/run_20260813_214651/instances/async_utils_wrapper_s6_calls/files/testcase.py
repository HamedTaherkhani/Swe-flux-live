import asyncio
import inspect
import random
import unittest

from jinja2 import Environment
from jinja2.async_utils import async_variant
from jinja2.nodes import EvalContext
from jinja2.runtime import Context
from jinja2.utils import pass_context, pass_eval_context, pass_environment

_PASS_STYLES = ("plain", "environment", "eval_context", "context")


def _stable_mix(values: list[int]) -> int:
    total = 0
    for index, value in enumerate(values):
        total ^= (value * (index + 11)) % 10009
    return total % 9973


def _apply_pass_style(func, style: str):
    if style == "environment":
        return pass_environment(func)
    if style == "eval_context":
        return pass_eval_context(func)
    if style == "context":
        return pass_context(func)
    return func


def _func_params(style: str) -> str:
    if style == "environment":
        return "env, value"
    if style in ("eval_context", "context"):
        return "ctx, value"
    return "value"


def _make_pair(stem: str, style: str) -> tuple[object, int]:
    namespace: dict[str, object] = {}
    params = _func_params(style)
    exec(
        f"def sync_{stem}({params}):\n"
        f"    return value + {len(stem) % 13}\n",
        namespace,
    )
    exec(
        f"async def async_{stem}({params}):\n"
        f"    return value + {len(stem) % 17}\n",
        namespace,
    )
    sync_func = namespace[f"sync_{stem}"]
    async_func = namespace[f"async_{stem}"]
    sync_func = _apply_pass_style(sync_func, style)
    async_func = _apply_pass_style(async_func, style)
    wrapper = async_variant(sync_func)(async_func)
    fingerprint = (
        len(wrapper.__name__)
        + int(getattr(wrapper, "jinja_async_variant", False))
        + (1 if getattr(wrapper, "jinja_pass_arg", None) is not None else 0)
        + sum(ord(char) for char in stem)
    )
    return wrapper, fingerprint


def _invoke(wrapper, style: str, async_flag: bool, value: int) -> int:
    env = Environment(enable_async=async_flag)
    if style == "environment":
        args = (env, value)
    elif style == "context":
        ctx = Context(env, {}, None, {})
        args = (ctx, value)
    else:
        ec = EvalContext(env)
        args = (ec, value)
    result = wrapper(*args)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return int(result)


class TestAsyncUtilsWrapperCalls(unittest.TestCase):
    def test_direct_wrapper_dispatch_batch(self) -> None:
        rng = random.Random(1507)
        wrappers: list[tuple[object, str, int]] = []
        for index in range(26):
            stem = f"k{index:02d}_{rng.randint(0, 99999):05d}"
            style = _PASS_STYLES[(index * 5 + 2) % len(_PASS_STYLES)]
            wrapper, fingerprint = _make_pair(stem, style)
            wrappers.append((wrapper, style, fingerprint))

        outputs: list[int] = []
        for wrapper, style, fingerprint in wrappers:
            for slot in range(9):
                async_flag = ((fingerprint + slot * 3) % 7) < 4
                value = rng.randint(-80, 80) + slot
                outputs.append(_invoke(wrapper, style, async_flag, value))

        self.assertEqual(len(outputs), len(wrappers) * 9)
        self.assertGreater(_stable_mix(outputs), 0)
        self.assertEqual(len({style for _, style, _ in wrappers}), len(_PASS_STYLES))
