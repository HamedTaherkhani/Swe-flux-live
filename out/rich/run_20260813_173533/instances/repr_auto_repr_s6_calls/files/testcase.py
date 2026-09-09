"""Direct exercise of auto_repr via bound __repr__ on @auto-decorated classes."""

import unittest
from random import Random

from rich.repr import auto


def _rich_node_class(seed: int, count: int) -> type:
    @auto
    class _RichNode:
        def __init__(self) -> None:
            self._seed = seed
            self._count = count

        def __rich_repr__(self):
            rng = Random(self._seed)
            for index in range(self._count):
                mode = (self._seed + index * 17 + rng.randint(0, 3)) % 9
                if mode == 0:

                    @auto
                    class _Dyn:
                        slot = index

                    yield f"k{index}", _Dyn
                elif mode == 1:
                    yield (f"only_{index}",)
                elif mode == 2:
                    yield None, rng.randint(0, 100)
                elif mode == 3:
                    default = rng.randint(1, 50)
                    yield "field", default, default
                elif mode == 4:
                    yield "field", rng.randint(0, 100), -1
                elif mode == 5:
                    yield rng.randint(0, 999)
                elif mode == 6:
                    yield "tag", {"n": index, "s": self._seed}
                elif mode == 7:
                    yield (
                        f"name_{index}",
                        tuple(rng.randint(0, 9) for _ in range(3)),
                    )
                else:

                    @auto(angular=True)
                    class _Ang:
                        value = index

                    yield f"ang_{index}", _Ang

    return _RichNode


def _angular_node_class(seed: int, count: int) -> type:
    @auto(angular=True)
    class _AngularNode:
        def __init__(self) -> None:
            self._seed = seed
            self._count = count

        def __rich_repr__(self):
            rng = Random(self._seed ^ 0xFF)
            for index in range(self._count):
                mode = (self._seed + index * 17 + rng.randint(0, 3)) % 9
                if mode == 0:

                    @auto
                    class _Dyn:
                        slot = index

                    yield f"k{index}", _Dyn
                elif mode == 1:
                    yield (f"only_{index}",)
                elif mode == 2:
                    yield None, rng.randint(0, 100)
                elif mode == 3:
                    default = rng.randint(1, 50)
                    yield "field", default, default
                elif mode == 4:
                    yield "field", rng.randint(0, 100), -1
                elif mode == 5:
                    yield rng.randint(0, 999)
                elif mode == 6:
                    yield "tag", {"n": index, "s": self._seed}
                elif mode == 7:
                    yield (
                        f"name_{index}",
                        tuple(rng.randint(0, 9) for _ in range(3)),
                    )
                else:

                    @auto(angular=True)
                    class _Ang:
                        value = index

                    yield f"ang_{index}", _Ang

    return _AngularNode


@auto
class AutoOnly:
    def __init__(self, a: int, b: int = 10, c: int = 20) -> None:
        self.a = a
        self.b = b
        self.c = c


class TestAutoReprExecutedPath(unittest.TestCase):
    def test_direct_auto_repr_invocations(self) -> None:
        seed_base = 0xC0DE
        instances: list = []
        for index in range(28):
            seed = seed_base + index * 31
            count = 18 + (index % 9)
            rich_cls = _rich_node_class(seed, count)
            angular_cls = _angular_node_class(seed, count)
            instances.append(rich_cls())
            instances.append(angular_cls())
            instances.append(AutoOnly(index, b=index % 7, c=index * 2))

        checksum = 0
        lengths: list[int] = []
        for instance in instances:
            repr_fn = instance.__repr__
            rendered = repr_fn()
            lengths.append(len(rendered))
            checksum += len(rendered) + sum(ord(ch) for ch in rendered[:24])

        self.assertEqual(len(instances), 84)
        self.assertGreater(max(lengths), 40)
        self.assertGreater(checksum, 100_000)
        self.assertGreater(sum(lengths), 5_000)
