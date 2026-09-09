import math
import unittest

from lark.utils import Serialize, _deserialize


_FIELD_NAMES = tuple(
    "field_" + str(index * index + 3 * index + 1)
    for index in range(17)
)
_EXCEPTION_MODULE = __import__("lark.exceptions", fromlist=["placeholder"])


class _Leaf(Serialize):
    __serialize_fields__ = _FIELD_NAMES


class _Record(Serialize):
    __serialize_fields__ = ("mode",) + _FIELD_NAMES
    __serialize_namespace__ = (_Leaf,)

    def _deserialize(self):
        selector = self.mode
        if selector == 3:
            self.marker = selector // (selector - selector)
        elif selector == 4:
            self.marker = [selector][selector]
        elif selector == 5:
            self.marker = int(chr(ord("q") + selector))
        elif selector == 6:
            self.marker = bytes([2 ** (selector + 2) - 1]).decode("ascii")
        elif selector == 7:
            self.marker = selector()
        elif selector == 8:
            self.marker = getattr(selector, "generated_" + str(selector))
        elif selector == 9:
            exception_name = "".join(("Grammar", "Error"))
            exception_class = getattr(_EXCEPTION_MODULE, exception_name)
            raise exception_class("generated record rejection")
        elif selector == 14:
            try:
                math.exp((selector + 1) ** (selector - 4))
            except Exception:
                self.marker = selector * selector
        elif selector == 16:
            self.marker = {selector: selector + 1}[selector - 1]
        else:
            self.marker = sum(
                getattr(self, name) for name in _FIELD_NAMES
            ) % (selector + 23)


class _Blocked(Serialize):
    __serialize_fields__ = ()

    def __new__(cls):
        return [cls][len(cls.__name__)]


_ROOT_NAMESPACE = {
    cls.__name__: cls for cls in (_Record, _Blocked)
}


class TestDeserializeExceptionAggregation(unittest.TestCase):
    def _valid_record(self, route, state):
        payload = {
            name: (state + index * index + route * (index + 1)) % 97
            for index, name in enumerate(_FIELD_NAMES)
        }
        payload["mode"] = route
        payload["__type__"] = _Record.__name__
        return payload

    def _leaf_payload(self, route, state):
        payload = {
            name: (state * (index + 2) + route + index) % 89
            for index, name in enumerate(_FIELD_NAMES)
        }
        payload["__type__"] = _Leaf.__name__
        return payload

    def _payload_for(self, route, state, memo):
        if route == 12:
            key = (state % 7) + 1
            memo[key] = ("memo", state * state + route)
            return {"__type__": _Record.__name__, "@": key}
        if route == 13:
            return {
                "__type__": _Record.__name__,
                "@": state + len(memo) + 101,
            }
        if route == 18:
            return {"__type__": _Blocked.__name__}

        payload = self._valid_record(route, state)
        selected = _FIELD_NAMES[(state + route * route) % len(_FIELD_NAMES)]
        if route == 1:
            del payload[selected]
        elif route == 2:
            payload[selected] = {"@": []}
        elif route == 10:
            payload[selected] = self._leaf_payload(route, state)
        elif route == 11:
            nested = self._leaf_payload(route, state)
            del nested[
                _FIELD_NAMES[(state * 3 + route) % len(_FIELD_NAMES)]
            ]
            payload[selected] = nested
        elif route == 15:
            payload[selected] = {
                "__type__": "_".join(("Absent", "Record")),
                "value": state,
            }
        elif route == 17:
            payload[selected] = [
                {
                    "left": (state + index) % 31,
                    "right": [route, index, state % (index + 2)],
                }
                for index in range((state % 5) + 4)
            ]
        return payload

    def _exercise(self, rounds, stride, offset, twist):
        memo = {}
        outcomes = []
        checksum = 0
        state = (rounds + offset + 1) * (twist + 3)

        for index in range(rounds):
            state = (
                state * (stride + 7)
                + index * index
                + twist * (index + 1)
                + offset
            ) % 997
            route = (index * stride + offset) % 20
            payload = self._payload_for(route, state, memo)
            try:
                value = _deserialize(payload, _ROOT_NAMESPACE, memo)
            except Exception as caught:
                outcomes.append(bool(str(caught)))
                checksum ^= (index + 1) * (len(str(caught)) + state)
            else:
                outcomes.append(False)
                checksum ^= (index + 1) * (len(repr(value)) + state)

        self.assertEqual(len(outcomes), rounds)
        self.assertTrue(any(outcomes))
        self.assertFalse(all(outcomes))
        self.assertIsInstance(checksum, int)

    def test_prime_stride_rotation(self):
        self._exercise(23, 3, 1, 2)

    def test_reverse_offset_walk(self):
        self._exercise(26, 19, 7, 4)

    def test_dense_seven_cycle(self):
        self._exercise(29, 7, 3, 5)

    def test_eleven_step_fold(self):
        self._exercise(31, 11, 9, 1)

    def test_thirteen_step_mix(self):
        self._exercise(27, 13, 4, 6)

    def test_seventeen_step_mix(self):
        self._exercise(25, 17, 12, 3)

    def test_low_offset_sweep(self):
        self._exercise(24, 9, 0, 7)

    def test_high_offset_sweep(self):
        self._exercise(28, 3, 18, 8)

    def test_odd_round_wrap(self):
        self._exercise(33, 7, 14, 2)

    def test_square_state_bias(self):
        self._exercise(30, 11, 6, 9)

    def test_coprime_long_walk(self):
        self._exercise(34, 13, 11, 4)

    def test_final_residue_walk(self):
        self._exercise(32, 17, 16, 5)
