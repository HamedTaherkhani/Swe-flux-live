import random
import unittest

from jinja2.async_utils import async_variant
from jinja2.utils import pass_context, pass_eval_context, pass_environment


_PASS_STYLES = ("plain", "environment", "eval_context", "context")


def _stable_mix(values: list[int]) -> int:
    total = 0
    for index, value in enumerate(values):
        total ^= (value * (index + 3)) % 10007
    return total % 1000


def _apply_pass_style(func, style: str):
    if style == "environment":
        return pass_environment(func)
    if style == "eval_context":
        return pass_eval_context(func)
    if style == "context":
        return pass_context(func)
    return func


def _make_pair(stem: str, style: str) -> tuple[object, int]:
    namespace: dict[str, object] = {}
    exec(
        f"def sync_{stem}(value):\n"
        f"    return value + {len(stem) % 9}\n",
        namespace,
    )
    exec(
        f"async def async_{stem}(value):\n"
        f"    return value + {len(stem) % 11}\n",
        namespace,
    )
    sync_func = namespace[f"sync_{stem}"]
    async_func = namespace[f"async_{stem}"]
    sync_func = _apply_pass_style(sync_func, style)
    wrapper = async_variant(sync_func)(async_func)
    fingerprint = (
        len(wrapper.__name__)
        + int(getattr(wrapper, "jinja_async_variant", False))
        + (1 if getattr(wrapper, "jinja_pass_arg", None) is not None else 0)
        + sum(ord(char) for char in stem)
    )
    return wrapper, fingerprint


def _build_batch(seed: int, count: int) -> tuple[list[object], int]:
    rng = random.Random(seed)
    wrappers: list[object] = []
    fingerprints: list[int] = []
    for index in range(count):
        stem = f"v{seed:03d}_{index:02d}_{rng.randint(0, 9999):04d}"
        style = _PASS_STYLES[(seed + index * 7) % len(_PASS_STYLES)]
        wrapper, fingerprint = _make_pair(stem, style)
        wrappers.append(wrapper)
        fingerprints.append(fingerprint)
    return wrappers, _stable_mix(fingerprints)


class TestAsyncVariantDecoratorDirect(unittest.TestCase):
    def test_plain_batch_alpha(self) -> None:
        wrappers, checksum = _build_batch(101, 18)
        self.assertEqual(len(wrappers), 18)
        self.assertEqual(checksum, 139)

    def test_environment_batch_beta(self) -> None:
        wrappers, checksum = _build_batch(203, 16)
        self.assertEqual(len(wrappers), 16)
        self.assertEqual(checksum, 120)

    def test_eval_context_batch_gamma(self) -> None:
        wrappers, checksum = _build_batch(307, 20)
        self.assertEqual(len(wrappers), 20)
        self.assertEqual(checksum, 678)

    def test_context_batch_delta(self) -> None:
        wrappers, checksum = _build_batch(409, 17)
        self.assertEqual(len(wrappers), 17)
        self.assertEqual(checksum, 89)

    def test_mixed_styles_epsilon(self) -> None:
        wrappers, checksum = _build_batch(503, 22)
        self.assertEqual(len(wrappers), 22)
        self.assertEqual(checksum, 268)

    def test_large_plain_zeta(self) -> None:
        wrappers, checksum = _build_batch(607, 24)
        self.assertEqual(len(wrappers), 24)
        self.assertEqual(checksum, 246)

    def test_large_environment_eta(self) -> None:
        wrappers, checksum = _build_batch(709, 19)
        self.assertEqual(len(wrappers), 19)
        self.assertEqual(checksum, 628)

    def test_large_eval_context_theta(self) -> None:
        wrappers, checksum = _build_batch(811, 21)
        self.assertEqual(len(wrappers), 21)
        self.assertEqual(checksum, 172)

    def test_large_context_iota(self) -> None:
        wrappers, checksum = _build_batch(913, 18)
        self.assertEqual(len(wrappers), 18)
        self.assertEqual(checksum, 946)

    def test_staggered_seeds_kappa(self) -> None:
        total_checksum = 0
        for offset in range(6):
            wrappers, checksum = _build_batch(1009 + offset * 17, 15)
            self.assertGreaterEqual(len(wrappers), 15)
            total_checksum ^= checksum
        self.assertEqual(total_checksum % 1000, 499)

    def test_nested_stride_lambda(self) -> None:
        rng = random.Random(1103)
        fingerprints: list[int] = []
        for block in range(5):
            for slot in range(16):
                stem = f"b{block:01d}s{slot:02d}r{rng.randint(0, 99999):05d}"
                style = _PASS_STYLES[(block * slot + slot) % len(_PASS_STYLES)]
                _wrapper, fingerprint = _make_pair(stem, style)
                fingerprints.append(fingerprint)
        self.assertEqual(_stable_mix(fingerprints), 223)

    def test_final_sweep_mu(self) -> None:
        rng = random.Random(1207)
        fingerprints: list[int] = []
        for index in range(30):
            stem = f"fin_{index:02d}_{rng.randint(0, 999999):06d}"
            style = _PASS_STYLES[rng.randint(0, len(_PASS_STYLES) - 1)]
            _wrapper, fingerprint = _make_pair(stem, style)
            fingerprints.append(fingerprint)
        self.assertEqual(_stable_mix(fingerprints), 624)
