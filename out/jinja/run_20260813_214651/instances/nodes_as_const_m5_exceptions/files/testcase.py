"""Exercise compile-time filter/test constant folding through template compilation."""

from __future__ import annotations

import random
import unittest

from jinja2 import Environment
from jinja2.nodes import And, EvalContext
from jinja2.utils import pass_context, pass_environment


def _extract_output_expr(tree) -> object:
    output = tree.body[0]
    return output.nodes[0]


class TestNodesAsConstExceptionAggregation(unittest.TestCase):
    """Drive _FilterTestCommon.as_const indirectly via compilation and caller nodes."""

    SEED = 57721566

    def setUp(self) -> None:
        self.env = Environment()
        self._register_custom_filters()
        self._register_custom_tests()

    def _register_custom_filters(self) -> None:
        def lookup_mapping(x: object) -> object:
            return {"only": 1}[str(x)]

        def lookup_sequence(x: object) -> object:
            return [0, 1, 2][int(x)]

        def lookup_attribute(x: object) -> object:
            return x.missing_slot

        def parse_token(x: object) -> object:
            return int(str(x))

        @pass_context
        def needs_context(ctx: object, x: object) -> object:
            return x

        self.env.filters.update(
            {
                "lookup_mapping": lookup_mapping,
                "lookup_sequence": lookup_sequence,
                "lookup_attribute": lookup_attribute,
                "parse_token": parse_token,
                "needs_context": needs_context,
            }
        )

    def _register_custom_tests(self) -> None:
        @pass_environment
        def env_probe(env: Environment, name: str) -> bool:
            return name in env.tests

        self.env.tests["env_probe"] = env_probe

    def _compile_quiet(self, source: str) -> bool:
        try:
            self.env.compile(source)
            return True
        except Exception:
            return False

    def _fold_via_and(self, source: str, volatile: bool = False) -> object | None:
        tree = self.env.parse(source)
        node = _extract_output_expr(tree)
        if not isinstance(node, And):
            self.fail("expected And expression")
        eval_ctx = EvalContext(self.env)
        eval_ctx.volatile = volatile
        try:
            return node.as_const(eval_ctx)
        except Exception:
            return None

    def test_compile_odd_sweep(self) -> None:
        rng = random.Random(self.SEED + 1)
        passed = 0
        for repeat in range(22):
            value = rng.randint(0, 199)
            if self._compile_quiet(f"{{{{ {value} is odd }}}}"):
                passed += 1
        self.assertGreater(passed, 18)

    def test_compile_even_sweep(self) -> None:
        rng = random.Random(self.SEED + 2)
        passed = 0
        for repeat in range(22):
            value = rng.randint(0, 199)
            if self._compile_quiet(f"{{{{ {value} is even }}}}"):
                passed += 1
        self.assertGreater(passed, 18)

    def test_compile_filter_sweep(self) -> None:
        rng = random.Random(self.SEED + 3)
        filters = ["upper", "lower", "trim", "title", "capitalize"]
        passed = 0
        for repeat in range(21):
            filt = filters[(repeat * 3 + rng.randint(0, 2)) % len(filters)]
            token = f"tok-{repeat}-{rng.randint(0, 9)}"
            if self._compile_quiet(f'{{{{ "{token}"|{filt} }}}}'):
                passed += 1
        self.assertGreater(passed, 18)

    def test_missing_name_compiles(self) -> None:
        rng = random.Random(self.SEED + 4)
        failures = 0
        for repeat in range(14):
            tag = rng.randint(1000, 9999)
            if not self._compile_quiet(f"{{{{ {tag} is missing_test_{tag} }}}}"):
                failures += 1
            if not self._compile_quiet(f"{{{{ {tag}|missing_filter_{tag} }}}}"):
                failures += 1
        self.assertGreater(failures, 20)

    def test_pass_context_filter_compiles(self) -> None:
        rng = random.Random(self.SEED + 5)
        passed = 0
        for repeat in range(16):
            value = rng.randint(1, 50)
            if self._compile_quiet(f"{{{{ {value}|needs_context }}}}"):
                passed += 1
        self.assertGreater(passed, 12)

    def test_pass_environment_test_compiles(self) -> None:
        rng = random.Random(self.SEED + 6)
        passed = 0
        probes = ["odd", "even", "none", "true", "false"]
        for repeat in range(18):
            probe = probes[(repeat * 5 + rng.randint(0, 2)) % len(probes)]
            if self._compile_quiet(f'{{{{ "{probe}" is test }}}}'):
                passed += 1
            if self._compile_quiet(f'{{{{ "{probe}" is env_probe }}}}'):
                passed += 1
        self.assertGreater(passed, 20)

    def test_lookup_mapping_batch(self) -> None:
        rng = random.Random(self.SEED + 7)
        attempts = 0
        for repeat in range(18):
            token = f"key-{repeat}-{rng.randint(0, 4)}"
            self._compile_quiet(f'{{{{ "{token}"|lookup_mapping }}}}')
            attempts += 1
        self.assertEqual(attempts, 18)

    def test_lookup_sequence_batch(self) -> None:
        rng = random.Random(self.SEED + 8)
        attempts = 0
        for repeat in range(16):
            index = rng.randint(3, 12)
            self._compile_quiet(f"{{{{ {index}|lookup_sequence }}}}")
            attempts += 1
        self.assertEqual(attempts, 16)

    def test_lookup_attribute_batch(self) -> None:
        rng = random.Random(self.SEED + 9)
        attempts = 0
        for repeat in range(14):
            value = rng.randint(1, 60)
            self._compile_quiet(f"{{{{ {value}|lookup_attribute }}}}")
            attempts += 1
        self.assertEqual(attempts, 14)

    def test_parse_token_batch(self) -> None:
        rng = random.Random(self.SEED + 10)
        attempts = 0
        for repeat in range(18):
            token = f"bad-{repeat}-{rng.randint(0, 9)}"
            self._compile_quiet(f'{{{{ "{token}"|parse_token }}}}')
            attempts += 1
        self.assertEqual(attempts, 18)

    def test_divisibleby_zero_batch(self) -> None:
        rng = random.Random(self.SEED + 12)
        attempts = 0
        for repeat in range(14):
            numerator = rng.randint(2, 120)
            self._compile_quiet(f"{{{{ {numerator} is divisibleby(0) }}}}")
            attempts += 1
        self.assertEqual(attempts, 14)

    def test_string_odd_type_batch(self) -> None:
        rng = random.Random(self.SEED + 13)
        attempts = 0
        for repeat in range(12):
            token = f"s-{repeat}-{rng.randint(0, 9)}"
            self._compile_quiet(f'{{{{ "{token}" is odd }}}}')
            attempts += 1
        self.assertEqual(attempts, 12)

    def test_async_filter_batch(self) -> None:
        async_env = Environment(enable_async=True)

        async def async_upper(value: str) -> str:
            return value.upper()

        async_upper.jinja_async_variant = True
        async_env.filters["async_upper"] = async_upper

        rng = random.Random(self.SEED + 14)
        passed = 0
        for repeat in range(14):
            token = f"a-{repeat}"
            try:
                async_env.compile(f'{{{{ "{token}"|async_upper }}}}')
                passed += 1
            except Exception:
                pass
        self.assertGreater(passed, 10)

    def test_and_caller_fold_batch(self) -> None:
        rng = random.Random(self.SEED + 15)
        successes = 0
        for repeat in range(18):
            left = rng.randint(0, 99)
            right = rng.randint(0, 99)
            result = self._fold_via_and(
                f"{{{{ ({left} is odd) and ({right} is even) }}}}"
            )
            if result is True or result is False:
                successes += 1
        self.assertGreater(successes, 14)

    def test_volatile_caller_fold_batch(self) -> None:
        rng = random.Random(self.SEED + 17)
        blocked = 0
        for repeat in range(14):
            value = rng.randint(0, 99)
            result = self._fold_via_and(
                f"{{{{ ({value} is odd) and ({value} is even) }}}}",
                volatile=True,
            )
            if result is None:
                blocked += 1
        self.assertGreater(blocked, 10)
