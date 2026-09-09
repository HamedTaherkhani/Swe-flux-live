from __future__ import annotations

import random
import unittest
from collections import defaultdict
from types import SimpleNamespace

from twisted.python.failure import Failure

from scrapy.http import Request, Response
from scrapy.pipelines.files import FilesPipeline


class _CountingStats:
    def __init__(self) -> None:
        self.values: defaultdict[str, int] = defaultdict(int)

    def inc_value(self, key: str) -> None:
        self.values[key] += 1


class _ScenarioPipeline(FilesPipeline):
    def __init__(self) -> None:
        self.crawler = SimpleNamespace(stats=_CountingStats())
        self.active_selector = -1
        self.active_variant = -1

    def inc_stats(self, status: str) -> None:
        if self.active_selector == 10:
            tokens: tuple[str, ...] = ()
            tokens[(self.active_variant % 3) + 1]
        super().inc_stats(status)

    def file_path(self, request, response=None, info=None, *, item=None) -> str:
        selector = request.meta["selector"]
        variant = request.meta["variant"]
        token = request.url.rsplit("/", 1)[-1]
        if selector == 3:
            if variant % 2:
                lookup: dict[str, str] = {}
                return lookup[token]
            parts: tuple[str, ...] = ()
            return parts[(variant % 4) + 1]
        if selector == 4:
            encoded = bytes(((variant % 31) + 224,))
            return encoded.decode("ascii")
        if selector == 5:
            denominator = len(token) - len(token)
            return f"files/{variant // denominator}"
        return f"files/{token}"

    async def file_downloaded(
        self, response, request, info, *, item=None
    ) -> str:
        selector = request.meta["selector"]
        variant = request.meta["variant"]
        token = request.url.rsplit("/", 1)[-1]
        if selector == 6:
            return str(int(token))
        if selector == 7:
            return "digest-" + variant
        if selector == 8:
            try:
                numerator = sum(response.body)
                numerator // (len(response.body) - len(response.body))
            except Exception:
                return self.media_failed(Failure(), request, info)
        if selector == 9:
            try:
                int(float("inf"))
            except Exception:
                pass
        return f"{sum(response.body):x}-{variant:x}"


class TestFilesMediaDownloaded(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.pipeline = _ScenarioPipeline()
        self.info = SimpleNamespace(spider=SimpleNamespace(name="qa-spider"))

    async def _exercise(self, plans: list[int], salt: int) -> None:
        outcomes: list[tuple[bool, bool, bool]] = []
        for ordinal, raw in enumerate(plans):
            mixed = (raw * raw + salt * (ordinal + 3) + (raw ^ salt)) & 0xFFFF
            selector = (mixed + ordinal * 7 + salt) % 11
            variant = (mixed * 13 + raw * 5 + ordinal) % 997
            url = f"https://example.invalid/batch/{salt:x}/asset-{variant:x}-{ordinal:x}.bin"
            request = Request(
                url,
                meta={"selector": selector, "variant": variant},
                headers={"Referer": f"https://origin.invalid/{mixed:x}"},
            )
            status = 400 + (variant % 99) if selector == 0 else 200
            body = b"" if selector == 1 else bytes(
                ((mixed + step * (ordinal + 5)) % 251) + 1
                for step in range((variant % 13) + 3)
            )
            flags = ["cached"] if (mixed + selector) % 4 == 0 else []
            response = Response(url, status=status, body=body, flags=flags)
            self.pipeline.active_selector = selector
            self.pipeline.active_variant = variant

            try:
                result = await self.pipeline.media_downloaded(
                    response,
                    request,
                    self.info,
                    item={"ordinal": ordinal, "mask": mixed % 17},
                )
            except Exception as exc:
                outcomes.append((False, bool(str(exc)), exc.__cause__ is not None))
            else:
                outcomes.append(
                    (
                        set(result) == {"url", "path", "checksum", "status"},
                        result["url"] == url,
                        bool(result["checksum"]),
                    )
                )

        self.assertEqual(len(outcomes), len(plans))
        self.assertTrue(any(row[0] for row in outcomes))
        self.assertTrue(any(not row[0] for row in outcomes))
        self.assertTrue(
            all(isinstance(flag, bool) for row in outcomes for flag in row)
        )
        self.assertGreater(sum(self.pipeline.crawler.stats.values.values()), 0)

    async def test_quadratic_shuffle(self) -> None:
        rng = random.Random(0x51A7)
        plans = [(index * index + rng.randrange(1, 500)) for index in range(23)]
        rng.shuffle(plans)
        await self._exercise(plans, 0x31)

    async def test_reverse_triangular(self) -> None:
        plans = [index * (index + 1) // 2 + 37 for index in range(20 + 9)]
        await self._exercise(list(reversed(plans)), 0x47)

    async def test_seeded_xor_walk(self) -> None:
        rng = random.Random(0x9D3)
        cursor = rng.randrange(100, 900)
        plans = []
        for index in range(31):
            cursor ^= rng.randrange(1, 1024) + index * 9
            plans.append(cursor)
        await self._exercise(plans, 0x59)

    async def test_modular_cubic_wave(self) -> None:
        plans = [
            (index**3 + 17 * index * index + 43) % 1231
            for index in range(27)
        ]
        await self._exercise(plans, 0x6D)

    async def test_interleaved_halves(self) -> None:
        base = [(index * 73 + index**2 * 5) % 1601 for index in range(25)]
        midpoint = len(base) // 2
        plans = [
            value
            for pair in zip(base[:midpoint], base[midpoint:], strict=False)
            for value in pair
        ]
        await self._exercise(plans, 0x83)

    async def test_accumulated_bit_rotations(self) -> None:
        accumulator = 0x2A5
        plans = []
        for index in range(21):
            accumulator = ((accumulator << 3) | (accumulator >> 7)) & 0x7FF
            plans.append(accumulator ^ (index * 41))
        await self._exercise(plans, 0x97)

    async def test_seeded_sample_permutation(self) -> None:
        rng = random.Random(0xD21)
        plans = rng.sample(range(50, 2500), sum((17, 16)))
        await self._exercise(plans, 0xA7)

    async def test_folded_squares(self) -> None:
        left = [index * index + 11 * index for index in range(1, 12 + 7)]
        plans = left + [
            value ^ (position * (20 + 9))
            for position, value in enumerate(left)
        ]
        await self._exercise(plans, 0xB5)

    async def test_lcg_stream(self) -> None:
        state = 0xACE
        plans = []
        for _ in range(24):
            state = (state * 109 + 89) % 4093
            plans.append(state)
        await self._exercise(plans, 0xC1)

    async def test_alternating_polynomial(self) -> None:
        plans = [
            (index * 61 + (index**2 if index % 2 else index**3)) % 2027
            for index in range(28)
        ]
        await self._exercise(plans, 0xD7)

    async def test_chunk_reversal(self) -> None:
        source = [(index * 97 + 13) % 1879 for index in range(24 + 6)]
        plans = [
            value
            for start in range(0, len(source), 5)
            for value in reversed(source[start : start + 5])
        ]
        await self._exercise(plans, 0xE3)

    async def test_difference_cascade(self) -> None:
        source = [
            (index**3 + 101 * index + 7) % (2800 + 201)
            for index in range(32)
        ]
        plans = [
            abs(right - left) + position * 17
            for position, (left, right) in enumerate(zip(source, source[1:]))
        ]
        await self._exercise(plans, 0xF1)
