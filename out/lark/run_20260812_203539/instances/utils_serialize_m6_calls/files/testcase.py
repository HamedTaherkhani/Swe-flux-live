import unittest

from lark.utils import Serialize


class _Leaf(Serialize):
    __serialize_fields__ = ("code", "weight", "tags")

    def __init__(self, code, weight, tags):
        self.code = code
        self.weight = weight
        self.tags = tags


class _Hooked(Serialize):
    __serialize_fields__ = ("label", "child", "bias")

    def __init__(self, label, child, bias):
        self.label = label
        self.child = child
        self.bias = bias

    def _serialize(self, result, memo):
        result["signature"] = sum(
            (index + 1) * ord(char) for index, char in enumerate(self.label)
        ) ^ (self.bias * self.bias)


class _Bundle(Serialize):
    __serialize_fields__ = ("items", "metadata", "hook")

    def __init__(self, items, metadata, hook):
        self.items = items
        self.metadata = metadata
        self.hook = hook


class TestSerializeCallGraphAggregation(unittest.TestCase):
    def _exercise(self, rounds, stride, offset, mode):
        state = (rounds + 3) * (offset + 5)
        leaves = []
        for index in range(rounds):
            state = (
                state * (stride + 11)
                + index * index
                + (mode + 1) * (index + offset)
            ) % 1009
            tags = [
                (state + stride * step + index) % 97
                for step in range(3 + ((state + mode) % 5))
            ]
            leaves.append(_Leaf(index * stride + offset, state, tags))

        items = []
        for index, leaf in enumerate(leaves):
            selector = (leaf.weight + index * stride + mode) % 4
            peer = leaves[(index * (mode + 2) + offset) % rounds]
            if selector == 0:
                items.append([leaf, peer, {"again": leaf}])
            elif selector == 1:
                items.append({"primary": leaf, "peers": [peer, leaf]})
            elif selector == 2:
                items.append((leaf, peer, (state + index) % 41))
            else:
                items.append(
                    {
                        "primary": [leaf],
                        "frozen": frozenset(
                            chr(97 + ((state + index + step) % 20))
                            for step in range(4)
                        ),
                    }
                )

        metadata = {
            "route": [
                {
                    "index": index,
                    "value": (leaf.weight * (index + 3) + mode) % 257,
                }
                for index, leaf in enumerate(leaves)
                if (leaf.weight + index + offset) % (mode % 3 + 2)
            ],
            "matrix": [
                [(row * stride + col * offset + mode) % 53 for col in range(6)]
                for row in range(5 + mode % 4)
            ],
        }
        hook = _Hooked(
            "".join(
                chr(65 + ((leaf.weight + index + mode) % 26))
                for index, leaf in enumerate(leaves[:9])
            ),
            leaves[(state + mode) % rounds],
            state + stride,
        )
        root = _Bundle(items, metadata, hook)

        data, memo = root.memo_serialize([_Leaf])

        self.assertIsInstance(data, dict)
        self.assertIsInstance(memo, dict)
        self.assertTrue(data.get("items"))
        self.assertTrue(memo)
        self.assertEqual(set(memo), set(range(len(memo))))
        checksum = sum(
            len(entry.get("tags", ())) + entry.get("weight", 0)
            for entry in memo.values()
        )
        self.assertGreater(checksum, rounds)

    def test_coprime_three_path(self):
        self._exercise(17, 3, 2, 0)

    def test_five_stride_offset(self):
        self._exercise(19, 5, 7, 1)

    def test_seven_stride_rotation(self):
        self._exercise(23, 7, 4, 2)

    def test_eleven_stride_fold(self):
        self._exercise(29, 11, 9, 3)

    def test_thirteen_stride_dense(self):
        self._exercise(31, 13, 6, 4)

    def test_seventeen_stride_sparse(self):
        self._exercise(27, 17, 12, 5)

    def test_reverse_bias_walk(self):
        self._exercise(21, 19, 15, 6)

    def test_square_offset_walk(self):
        self._exercise(25, 9, 16, 7)

    def test_low_offset_cycle(self):
        self._exercise(33, 15, 1, 8)

    def test_high_offset_cycle(self):
        self._exercise(35, 21, 18, 9)

    def test_residue_mix_cycle(self):
        self._exercise(37, 23, 11, 10)

    def test_final_long_cycle(self):
        self._exercise(39, 25, 14, 11)


if __name__ == "__main__":
    unittest.main()
