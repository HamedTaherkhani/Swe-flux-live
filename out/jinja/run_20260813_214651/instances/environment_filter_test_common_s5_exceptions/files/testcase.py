import builtins
import random
import unittest

from jinja2 import (
    DictLoader,
    Environment,
    Undefined,
    pass_context,
    pass_environment,
    pass_eval_context,
)


def _builtin_exc_types() -> tuple[type[BaseException], ...]:
    return tuple(
        getattr(builtins, name)
        for name in sorted(dir(builtins))
        if isinstance(getattr(builtins, name), type)
        and issubclass(getattr(builtins, name), BaseException)
        and getattr(builtins, name).__module__ == "builtins"
        and name[0].isupper()
    )


_BUILTIN_EXC_TYPES = _builtin_exc_types()


def _jinja_exc_type(index: int) -> type[BaseException]:
    import jinja2.exceptions as exc_mod

    candidates = [
        getattr(exc_mod, name)
        for name in sorted(dir(exc_mod))
        if isinstance(getattr(exc_mod, name), type)
        and issubclass(getattr(exc_mod, name), BaseException)
        and getattr(exc_mod, name).__module__ == exc_mod.__name__
    ]
    return candidates[index % len(candidates)]


def _build_operations(seed: int, operation_count: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    return [(rng.randint(0, 8), index) for index in range(operation_count)]


@pass_context
def _ctx_offset(ctx, value: int) -> int:
    return value + int(ctx.get("offset", 0))


@pass_eval_context
def _eval_scale(eval_ctx, value: int) -> int:
    return value * (3 if eval_ctx.autoescape else 2)


@pass_environment
def _env_tag_len(env, value: str) -> int:
    return len(value) + len(env.block_start_string)


def _simple_square(value: int) -> int:
    return value * value


def _is_even(value: int) -> bool:
    return value % 2 == 0


class TestEnvironmentFilterTestDispatch(unittest.TestCase):
    def test_indirect_filter_and_test_dispatch(self) -> None:
        env = Environment(loader=DictLoader({"probe": "{{ n }}"}))
        env.filters["ctx_offset"] = _ctx_offset
        env.filters["eval_scale"] = _eval_scale
        env.filters["env_tag_len"] = _env_tag_len
        env.filters["simple_square"] = _simple_square
        env.tests["is_even"] = _is_even

        template = env.get_template("probe")
        context = template.new_context({"n": 7, "offset": 4})

        operations = _build_operations(seed=20240814, operation_count=32)
        checksum = 0
        failure_count = 0

        for variant, index in operations:
            value = (index * 11 + variant * 3) % 97
            if variant == 0:
                result = env.call_filter("simple_square", value)
                checksum ^= result + index
            elif variant == 1:
                result = env.call_filter("ctx_offset", value, context=context)
                checksum ^= result * 3 + index
            elif variant == 2:
                result = env.call_filter("eval_scale", value, context=context)
                checksum ^= result - index
            elif variant == 3:
                result = env.call_filter("env_tag_len", str(value))
                checksum ^= result + variant
            elif variant == 4:
                truth = env.call_test("is_even", value)
                checksum ^= int(truth) * 17 + index
            elif variant == 5:
                missing = Undefined(name=f"slot_{index}")
                try:
                    env.call_filter(missing, value)
                except BaseException:
                    failure_count += 1
                checksum ^= index * 5 + 1
            elif variant == 6:
                exc_type = _BUILTIN_EXC_TYPES[index % len(_BUILTIN_EXC_TYPES)]
                missing = Undefined(name=f"gap_{index}", exc=exc_type)
                try:
                    env.call_test(missing, value)
                except BaseException:
                    failure_count += 1
                checksum ^= index * 7 + 2
            elif variant == 7:
                exc_type = _jinja_exc_type(index)
                missing = Undefined(name=f"hole_{index}", exc=exc_type)
                try:
                    env.call_filter(missing, value)
                except BaseException:
                    failure_count += 1
                checksum ^= index * 11 + 3
            else:
                try:
                    env.call_filter("ctx_offset", value)
                except BaseException:
                    failure_count += 1
                checksum ^= index * 13 + 4

        self.assertEqual(checksum, 4996)
        self.assertEqual(failure_count, 12)
