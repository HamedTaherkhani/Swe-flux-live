import random
import unittest

from jinja2 import Environment


def _stable_hash(text: str) -> int:
    digest = 0
    for char in text:
        digest = (digest * 131 + ord(char)) % 10007
    return digest


def _register_programmatic_tests(env: Environment, count: int, seed: int) -> None:
    rng = random.Random(seed)
    for index in range(count):
        key = f"q{index:03d}"
        env.tests[key] = lambda value, _index=index, _rng=rng: (_index + int(bool(value))) % 7 == 0
    for base in range(count):
        for depth in range(2, 7):
            parts = [f"q{(base + offset) % count:03d}" for offset in range(depth)]
            dotted = ".".join(parts)
            env.tests[dotted] = lambda value, _base=base, _depth=depth: (_base + _depth) % 5 == 0


def _make_dotted_name(base: int, depth: int, count: int) -> str:
    return ".".join(f"q{(base + offset) % count:03d}" for offset in range(depth))


def _build_expression_batch(
    seed: int,
    batch_size: int,
    count: int,
    *,
    allow_negated: bool,
    allow_paren: bool,
    allow_implicit: bool,
    allow_filters: bool,
) -> list[str]:
    rng = random.Random(seed)
    expressions: list[str] = []
    for index in range(batch_size):
        base = (seed * 17 + index * 13) % count
        depth = 1 + (index % 6)
        test_name = _make_dotted_name(base, depth, count)
        subject = f"v{index % 11}"
        variant = rng.randint(0, 5)
        if allow_filters and variant == 0:
            expressions.append(f"{subject}|length is {test_name}")
        elif allow_negated and variant == 1:
            expressions.append(f"{subject} is not {_make_dotted_name(base + 3, 1, count)}")
        elif allow_paren and variant == 2:
            expressions.append(
                f"{subject} is {_make_dotted_name(base + 5, 1, count)}({1 + index % 9})"
            )
        elif allow_implicit and variant == 3:
            expressions.append(
                f"{subject} is {_make_dotted_name(base + 7, 1, count)} v{(index + 2) % 11}"
            )
        elif variant == 4:
            expressions.append(f"{subject} is {test_name}")
        else:
            expressions.append(
                f"({subject} + v{(index + 4) % 11}) is {_make_dotted_name(base + 1, depth, count)}"
            )
    return expressions


def _parse_variable_expressions(env: Environment, expressions: list[str]) -> int:
    checksum = 0
    for index, expression in enumerate(expressions):
        source = f"{{{{ {expression} }}}}"
        module = env.parse(source, name=f"var_{index}")
        checksum ^= len(module.body) * (index + 7) + _stable_hash(expression)
    return checksum


def _parse_conditional_blocks(env: Environment, conditions: list[str]) -> int:
    checksum = 0
    for index, condition in enumerate(conditions):
        source = (
            f"{{% if {condition} %}}T{{% elif {condition} %}}F{{% else %}}X{{% endif %}}"
        )
        module = env.parse(source, name=f"cond_{index}")
        checksum ^= len(module.body) * (index + 11) + _stable_hash(condition)
    return checksum


class TestParserParseTestIndirect(unittest.TestCase):
    TEST_COUNT = 48

    def setUp(self) -> None:
        self.env = Environment()
        _register_programmatic_tests(self.env, self.TEST_COUNT, seed=20240814)

    def test_batch_negated_and_plain(self) -> None:
        expressions = _build_expression_batch(
            101,
            18,
            self.TEST_COUNT,
            allow_negated=True,
            allow_paren=False,
            allow_implicit=False,
            allow_filters=False,
        )
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 535)

    def test_batch_paren_arguments(self) -> None:
        expressions = _build_expression_batch(
            203,
            20,
            self.TEST_COUNT,
            allow_negated=False,
            allow_paren=True,
            allow_implicit=False,
            allow_filters=False,
        )
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 869)

    def test_batch_implicit_arguments(self) -> None:
        expressions = _build_expression_batch(
            307,
            16,
            self.TEST_COUNT,
            allow_negated=False,
            allow_paren=False,
            allow_implicit=True,
            allow_filters=False,
        )
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 567)

    def test_batch_deep_dotted_names(self) -> None:
        expressions = [
            f"v{index} is {_make_dotted_name(100 + index, 2 + index % 5, self.TEST_COUNT)}"
            for index in range(24)
        ]
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 615)

    def test_batch_shallow_dotted_names(self) -> None:
        expressions = [
            f"v{index} is {_make_dotted_name(200 + index * 3, 2, self.TEST_COUNT)}"
            for index in range(22)
        ]
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 122)

    def test_batch_filter_prefix_chain(self) -> None:
        expressions = _build_expression_batch(
            409,
            14,
            self.TEST_COUNT,
            allow_negated=False,
            allow_paren=False,
            allow_implicit=False,
            allow_filters=True,
        )
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 158)

    def test_batch_parenthesized_subjects(self) -> None:
        expressions = [
            f"(v{index} + v{(index + 3) % 11}) is "
            f"{_make_dotted_name(300 + index, 1 + index % 4, self.TEST_COUNT)}"
            for index in range(20)
        ]
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 431)

    def test_batch_boolean_combinations(self) -> None:
        rng = random.Random(509)
        expressions = []
        for index in range(24):
            left = _make_dotted_name(400 + index, 1 + index % 3, self.TEST_COUNT)
            right = _make_dotted_name(420 + index, 1 + (index + 2) % 4, self.TEST_COUNT)
            joiner = "and" if rng.randint(0, 1) == 0 else "or"
            expressions.append(f"v{index % 9} is {left} {joiner} v{(index + 1) % 9} is {right}")
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 118)

    def test_if_blocks_with_generated_tests(self) -> None:
        conditions = [
            f"v{index} is {_make_dotted_name(500 + index, 2 + index % 4, self.TEST_COUNT)}"
            for index in range(16)
        ]
        checksum = _parse_conditional_blocks(self.env, conditions)
        self.assertEqual(checksum % 1000, 657)

    def test_if_blocks_with_negated_tests(self) -> None:
        conditions = [
            f"v{index} is not {_make_dotted_name(600 + index, 1 + index % 3, self.TEST_COUNT)}"
            for index in range(14)
        ]
        checksum = _parse_conditional_blocks(self.env, conditions)
        self.assertEqual(checksum % 1000, 6)

    def test_mixed_variant_sweep(self) -> None:
        expressions = _build_expression_batch(
            701,
            30,
            self.TEST_COUNT,
            allow_negated=True,
            allow_paren=True,
            allow_implicit=True,
            allow_filters=True,
        )
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 835)

    def test_large_seeded_expression_mix(self) -> None:
        rng = random.Random(803)
        expressions = []
        for index in range(40):
            base = rng.randint(0, self.TEST_COUNT - 1)
            depth = 1 + rng.randint(0, 5)
            test_name = _make_dotted_name(base, depth, self.TEST_COUNT)
            subject = f"v{index % 13}"
            mode = rng.randint(0, 4)
            if mode == 0:
                expressions.append(f"{subject} is not {_make_dotted_name(base + 1, 1, self.TEST_COUNT)}")
            elif mode == 1:
                expressions.append(f"{subject} is {test_name}")
            elif mode == 2:
                expressions.append(
                    f"{subject} is {_make_dotted_name(base + 2, 1, self.TEST_COUNT)}({1 + index % 8})"
                )
            elif mode == 3:
                expressions.append(
                    f"{subject}|length is {_make_dotted_name(base + 4, 1 + index % 3, self.TEST_COUNT)}"
                )
            else:
                expressions.append(
                    f"({subject} + v{(index + 5) % 13}) is {test_name}"
                )
        checksum = _parse_variable_expressions(self.env, expressions)
        self.assertEqual(checksum % 1000, 816)
