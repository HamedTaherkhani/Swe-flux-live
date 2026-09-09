import hashlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_identifier_pattern import build_pattern


def _range_count_for_slot(seed: str, slot: int) -> int:
    digest = hashlib.blake2b(
        f"{seed}:range_count:{slot}".encode(), digest_size=2
    ).hexdigest()
    return 18 + (int(digest, 16) % 11)


def _build_ranges(seed: str, slot: int) -> list[tuple[str, str]]:
    count = _range_count_for_slot(seed, slot)
    digest = hashlib.blake2b(
        f"{seed}:ranges:{slot}".encode(), digest_size=64
    ).hexdigest()
    ranges: list[tuple[str, str]] = []

    for idx in range(count):
        byte = int(digest[idx * 2 : idx * 2 + 2], 16)
        kind = byte % 3
        base = 0x300 + (int(digest[(idx + 1) * 2 : (idx + 3) * 2], 16) % 400)
        if kind == 0:
            ranges.append((chr(base), chr(base)))
        elif kind == 1:
            ranges.append((chr(base), chr(base + 1)))
        else:
            ranges.append((chr(base), chr(base + 3 + byte % 8)))

    return ranges


def _invocation_count(seed: str) -> int:
    digest = hashlib.blake2b(f"{seed}:invocations".encode(), digest_size=1).hexdigest()
    return 7 + (int(digest, 16) % 5)


class BuildPatternS1CfgTest(unittest.TestCase):
    def test_build_pattern_middle_invocation_line_path(self) -> None:
        seed = "gid_bp_cfg_seed"
        outputs: list[str] = []
        for slot in range(_invocation_count(seed)):
            outputs.append(build_pattern(_build_ranges(seed, slot)))

        self.assertEqual(len(outputs), _invocation_count(seed))
        self.assertTrue(all(isinstance(item, str) for item in outputs))
        self.assertGreater(sum(len(item) for item in outputs), 0)
        checksum = hashlib.sha256("".join(outputs).encode()).hexdigest()
        self.assertEqual(len(checksum), 64)
