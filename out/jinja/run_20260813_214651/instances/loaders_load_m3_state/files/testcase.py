"""Indirect template loading via ChoiceLoader and PrefixLoader composite loaders."""

from __future__ import annotations

import hashlib
import random
import tempfile
import unittest

from jinja2 import Environment
from jinja2.bccache import FileSystemBytecodeCache
from jinja2.loaders import ChoiceLoader, DictLoader, PrefixLoader


class TestBaseLoaderLoadProgramState(unittest.TestCase):
    """Drive inherited loader.load through composite loaders with seeded workloads."""

    SEED = 27182818

    @classmethod
    def _body(cls, tag: str, width: int, rng: random.Random) -> str:
        span = max(3, width + rng.randint(0, 2))
        coeffs = [((idx + 1) * (len(tag) + 3) + rng.randint(0, 5)) for idx in range(span)]
        total = sum(coeffs)
        parity = total % (len(tag) + 2)
        return (
            "{% set acc = namespace(v=0) %}"
            "{% for item in range(" + str(span) + ") %}"
            "{% set acc.v = acc.v + item * " + str(parity + 1) + " %}"
            "{% endfor %}"
            "{{ acc.v }}-{{ '" + tag + "'|length }}-{{ " + str(parity) + " }}"
        )

    @classmethod
    def _mapping(cls, prefix: str, count: int, rng: random.Random) -> dict[str, str]:
        return {
            f"{prefix}-{idx:03d}.jinja": cls._body(f"{prefix}{idx}", idx % 9, rng)
            for idx in range(count)
        }

    @staticmethod
    def _digest(mapping: dict[str, str]) -> str:
        joined = "\n".join(f"{k}:{mapping[k]}" for k in sorted(mapping))
        return hashlib.sha256(joined.encode()).hexdigest()[:12]

    def _bare_env(self, *, bytecode_cache=None) -> Environment:
        return Environment(bytecode_cache=bytecode_cache)

    def test_choice_primary_hits(self) -> None:
        rng = random.Random(self.SEED + 2)
        primary = self._mapping("alpha", 20, rng)
        secondary = self._mapping("beta", 6, rng)
        env = self._bare_env()
        loader = ChoiceLoader([DictLoader(primary), DictLoader(secondary)])
        names = sorted(primary.keys())
        for repeat in range(18):
            name = names[(repeat * 7 + 3) % len(names)]
            tpl = loader.load(env, name)
            self.assertTrue(callable(tpl.render))

    def test_choice_secondary_fallback(self) -> None:
        rng = random.Random(self.SEED + 9)
        primary = self._mapping("ghost", 4, rng)
        secondary = self._mapping("gamma", 18, rng)
        env = self._bare_env()
        loader = ChoiceLoader([DictLoader(primary), DictLoader(secondary)])
        names = sorted(secondary.keys())
        for repeat in range(17):
            name = names[(repeat * 5 + 1) % len(names)]
            tpl = loader.load(env, name)
            self.assertRegex(tpl.name, r"\.jinja$")

    def test_choice_with_slot_globals(self) -> None:
        rng = random.Random(self.SEED + 14)
        mapping = self._mapping("slot", 14, rng)
        env = self._bare_env()
        loader = ChoiceLoader([DictLoader(mapping)])
        names = list(mapping.keys())
        for repeat in range(16):
            name = names[(repeat * 3 + 2) % len(names)]
            slot = (repeat * 11 + 7) % 23
            tpl = loader.load(env, name, globals={"slot": slot, "phase": repeat % 5})
            self.assertEqual(tpl.globals.get("slot"), slot)

    def test_choice_none_globals_batches(self) -> None:
        rng = random.Random(self.SEED + 21)
        mapping = self._mapping("none", 16, rng)
        env = self._bare_env()
        loader = ChoiceLoader([DictLoader(mapping)])
        names = list(mapping.keys())
        for repeat in range(19):
            name = names[(repeat * 9 + 4) % len(names)]
            tpl = loader.load(env, name, globals=None)
            self.assertIsNotNone(tpl)

    def test_prefix_single_shard(self) -> None:
        rng = random.Random(self.SEED + 28)
        shard = self._mapping("shard", 15, rng)
        env = self._bare_env()
        loader = PrefixLoader({"app": DictLoader(shard)})
        names = list(shard.keys())
        for repeat in range(18):
            local = names[(repeat * 6 + 1) % len(names)]
            tpl = loader.load(env, f"app/{local}")
            self.assertTrue(tpl.name.endswith(local.split("/")[-1]))

    def test_prefix_multi_roots(self) -> None:
        rng = random.Random(self.SEED + 35)
        left = self._mapping("left", 10, rng)
        right = self._mapping("right", 12, rng)
        env = self._bare_env()
        loader = PrefixLoader(
            {
                "l": DictLoader(left),
                "r": DictLoader(right),
            }
        )
        for repeat in range(20):
            if repeat % 2 == 0:
                local = sorted(left.keys())[(repeat * 4) % len(left)]
                tpl = loader.load(env, f"l/{local}")
            else:
                local = sorted(right.keys())[(repeat * 5 + 2) % len(right)]
                tpl = loader.load(env, f"r/{local}")
            self.assertIn(".jinja", tpl.name)

    def test_prefix_with_overlay_globals(self) -> None:
        rng = random.Random(self.SEED + 42)
        mapping = self._mapping("overlay", 13, rng)
        env = self._bare_env()
        loader = PrefixLoader({"pkg": DictLoader(mapping)})
        names = list(mapping.keys())
        for repeat in range(17):
            name = names[(repeat * 8 + 3) % len(names)]
            marker = repeat * 13 + 5
            tpl = loader.load(
                env,
                f"pkg/{name}",
                globals={"marker": marker, "band": repeat % 4},
            )
            self.assertEqual(tpl.globals.get("marker"), marker)

    def test_choice_three_tier_probe(self) -> None:
        rng = random.Random(self.SEED + 49)
        tier_a = self._mapping("ta", 5, rng)
        tier_b = self._mapping("tb", 8, rng)
        tier_c = self._mapping("tc", 11, rng)
        env = self._bare_env()
        loader = ChoiceLoader(
            [DictLoader(tier_a), DictLoader(tier_b), DictLoader(tier_c)]
        )
        pools = [sorted(tier_a.keys()), sorted(tier_b.keys()), sorted(tier_c.keys())]
        for repeat in range(21):
            tier = repeat % 3
            name = pools[tier][(repeat * 7 + tier) % len(pools[tier])]
            tpl = loader.load(env, name)
            self.assertIn(name, tpl.name)

    def test_bytecode_cache_cold_loads(self) -> None:
        rng = random.Random(self.SEED + 56)
        mapping = self._mapping("cold", 14, rng)
        with tempfile.TemporaryDirectory() as tmp:
            bcc = FileSystemBytecodeCache(tmp)
            env = self._bare_env(bytecode_cache=bcc)
            loader = ChoiceLoader([DictLoader(mapping)])
            names = sorted(mapping.keys())
            for repeat in range(16):
                name = names[(repeat * 11 + 5) % len(names)]
                tpl = loader.load(env, name)
                self.assertGreater(len(self._digest(mapping)), 8)
                self.assertTrue(callable(tpl.render))

    def test_bytecode_cache_warm_reload(self) -> None:
        rng = random.Random(self.SEED + 63)
        mapping = self._mapping("warm", 12, rng)
        with tempfile.TemporaryDirectory() as tmp:
            bcc = FileSystemBytecodeCache(tmp)
            env = self._bare_env(bytecode_cache=bcc)
            loader = ChoiceLoader([DictLoader(mapping)])
            names = sorted(mapping.keys())
            for name in names:
                loader.load(env, name)
            for repeat in range(18):
                name = names[(repeat * 5 + 1) % len(names)]
                tpl = loader.load(env, name)
                self.assertIsNotNone(tpl.render)

    def test_wide_mapping_sweep(self) -> None:
        rng = random.Random(self.SEED + 70)
        mapping = self._mapping("wide", 26, rng)
        env = self._bare_env()
        loader = ChoiceLoader([DictLoader(mapping)])
        ordered = sorted(mapping.keys())
        for repeat in range(24):
            name = ordered[(repeat * 9 + 7) % len(ordered)]
            tpl = loader.load(env, name, globals={"sweep": repeat})
            self.assertEqual(tpl.globals.get("sweep"), repeat)

    def test_mixed_empty_and_none_globals(self) -> None:
        rng = random.Random(self.SEED + 77)
        mapping = self._mapping("mixg", 11, rng)
        env = self._bare_env()
        loader = ChoiceLoader([DictLoader(mapping)])
        names = list(mapping.keys())
        for repeat in range(18):
            name = names[(repeat * 4 + 1) % len(names)]
            if repeat % 3 == 0:
                tpl = loader.load(env, name, globals={})
            elif repeat % 3 == 1:
                tpl = loader.load(env, name, globals=None)
            else:
                tpl = loader.load(env, name, globals={"tick": repeat})
            self.assertIsNotNone(tpl)
