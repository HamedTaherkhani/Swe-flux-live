import math
import unittest

from lark import Tree
from lark.visitors import Transformer_NonRecursive


_EXCEPTION_MODULE = __import__("lark.exceptions", fromlist=["placeholder"])


class _WrappedAction:
    def visit_wrapper(self, callback, data, children, meta):
        value = children[0]
        if value % (2 * 2) == 0:
            return value + len(data)
        return value // (value - value)


class _RoutedTransformer(Transformer_NonRecursive):
    def __getattr__(self, name):
        marker, separator, encoded = name.partition("_")
        if marker != "route" or not separator:
            raise AttributeError(name)

        code = int(encoded)
        if code == 3 * 4:
            raise AttributeError(name)
        if code == 3 * 3 + 2:
            return _WrappedAction()

        def action(children):
            value = children[0]
            if code == 0:
                return value + len(children)
            if code == 1:
                return value // (value - value)
            if code == 2:
                return [value][value + 1]
            if code == 3:
                return int(chr(ord("q") + value))
            if code == 2 * 2:
                return bytes([2 ** (2 * 2 * 2) - 1]).decode("ascii")
            if code == 5:
                return value()
            if code == 2 * 3:
                return getattr(value, "field_" + str(value))
            if code == 7:
                assert value < 0
                return value
            if code == 2 * 2 * 2:
                exception_name = "".join(("Grammar", "Error"))
                exception_class = getattr(_EXCEPTION_MODULE, exception_name)
                raise exception_class("generated callback rejection")
            if code == 3 * 3:
                try:
                    math.exp((value + 1) ** (3 * 3 + 1))
                except Exception:
                    return value * value
            if code == 2 * 5:
                return {value: value + 1}[value - 1]
            raise RuntimeError("unreachable route")

        return action


class TestTransformerExceptionAggregation(unittest.TestCase):
    def _exercise(self, span, salt, twist):
        rounds = (span + 2) * (2 + salt % 3)
        state = (salt + 1) * (span + twist + 1)
        outcomes = []

        for index in range(rounds):
            state = (
                state * (salt + 3) + index * (twist + 1) + span
            ) % (3 * 3 * 3 + 2)
            route = (state + index * index + salt * twist) % (3 * 4 + 1)
            value = (state + index + twist) % 7 + 1
            tree = Tree("route_" + str(route), [value])
            try:
                _RoutedTransformer().transform(tree)
            except Exception as caught:
                outcomes.append(bool(str(caught)))
            else:
                outcomes.append(False)

        self.assertEqual(len(outcomes), rounds)
        self.assertTrue(any(outcomes))
        self.assertFalse(all(outcomes))

    def test_short_prime_stride(self):
        self._exercise(3, 1, 2)

    def test_even_state_rotation(self):
        self._exercise(4, 2, 1)

    def test_wide_coprime_walk(self):
        self._exercise(5, 3, 4)

    def test_dense_low_salt(self):
        self._exercise(6, 1, 5)

    def test_high_salt_fold(self):
        self._exercise(7, 4, 2)

    def test_balanced_diagonal(self):
        self._exercise(5, 5, 5)

    def test_narrow_reverse_bias(self):
        self._exercise(3, 6, 4)

    def test_long_odd_stride(self):
        self._exercise(7, 2, 6)

    def test_square_seed_mix(self):
        self._exercise(4, 7, 3)

    def test_sparse_route_cycle(self):
        self._exercise(6, 8, 1)

    def test_offset_wraparound(self):
        self._exercise(5, 4, 7)

    def test_final_residue_sweep(self):
        self._exercise(7, 5, 3)
