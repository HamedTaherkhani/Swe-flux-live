"""Direct exercise of native_concat with seeded programmatic inputs."""

from __future__ import annotations

import hashlib
import random
import unittest
from types import GeneratorType

from jinja2.nativetypes import native_concat


class TestNativeConcatProgramState(unittest.TestCase):
    """Drive native_concat through varied branches with programmatic inputs."""

    SEED = 31415926
    ROUNDS = 25

    @classmethod
    def _gen_parts(cls, rng: random.Random, span: int) -> list[str]:
        return [f"{(idx * 3 + rng.randint(0, 4)) % 10}" for idx in range(span)]

    @classmethod
    def _stream(cls, parts: list[str]) -> GeneratorType:
        for part in parts:
            yield part

    def test_native_concat_programmatic_rounds(self) -> None:
        rng = random.Random(self.SEED)
        checksum = 0
        for i in range(self.ROUNDS):
            mod = (i * 5 + rng.randint(0, 7)) % 9
            if mod == 0:
                out = native_concat([])
            elif mod == 1:
                out = native_concat([42 + i])
            elif mod == 2:
                out = native_concat([str(100 + i)])
            elif mod == 3:
                parts = self._gen_parts(rng, 18)
                out = native_concat(self._stream(parts))
            elif mod == 4:
                inner = [f'"{i}-{j}"' for j in range(12)]
                out = native_concat(self._stream(["["] + inner + ["]"]))
            elif mod == 5:
                parts = [str((i + j) * 7) for j in range(20)]
                out = native_concat(parts)
            elif mod == 6:
                out = native_concat(
                    self._stream([f"not_valid_{i}_", str(i * 3), "_suffix"])
                )
            elif mod == 7:
                out = native_concat(
                    self._stream(["(", str(i), ",", str(i * 2), ")"])
                )
            else:
                parts = [f"{(i + j) % 3}" for j in range(25)]
                out = native_concat(self._stream(parts))
            tag = sum(ord(c) for c in type(out).__name__)
            checksum ^= tag ^ (len(repr(out)) % 997)
        digest = hashlib.sha256(str(checksum).encode()).hexdigest()[:12]
        self.assertEqual(digest, "6ea2fdb3399f")
        self.assertNotEqual(checksum, 0)
