import hashlib
import os
import unittest

from rich._unicode_data import load
from rich._unicode_data._versions import VERSIONS


def _digest(seed: int, label: str) -> bytes:
    return hashlib.sha256(f"unicode-load-s5-{seed}-{label}".encode()).digest()


def _build_version_specs(seed: int, count: int) -> list[str]:
    digest = _digest(seed, "versions")
    specs: list[str] = []
    for index in range(count):
        branch = (digest[index % len(digest)] + index * 7) % 8
        slot_a = digest[(index * 3 + 1) % len(digest)]
        slot_b = digest[(index * 5 + 9) % len(digest)]
        if branch == 0:
            specs.append("auto")
        elif branch == 1:
            specs.append("latest")
        elif branch == 2:
            specs.append(VERSIONS[(slot_a + index) % len(VERSIONS)])
        elif branch == 3:
            specs.append(f"bad-token-{slot_a}-{index}")
        elif branch == 4:
            specs.append(f"{12 + (index % 6)}.{index % 4}.{slot_b % 5}")
        elif branch == 5:
            specs.append(f"x{slot_a}.{slot_b}")
        elif branch == 6:
            specs.append(f"{slot_a}.{slot_b}.{index % 9}")
        else:
            specs.append(f"unicode-{index}-{slot_a:02x}")
    return specs


def _invalid_env_version(seed: int, index: int) -> str:
    digest = _digest(seed, f"env-{index}")
    return f"env-bad-{digest[0]}-{digest[1]}-{index}"


def _failure_slot(seed: int, count: int) -> int:
    digest = _digest(seed, "failure-slot")
    return 5 + (digest[2] % (count - 10))


def _failure_non_string(seed: int) -> int:
    digest = _digest(seed, "failure-object")
    return 400 + (digest[3] % 200) + (digest[4] % 17) * 3


def _table_fingerprint(tables: list) -> int:
    total = 0
    for table in tables:
        total += len(table.widths)
        for start, end, width in table.widths[:48]:
            total += start + end * 3 + width * 5
    return total


class UnicodeDataLoadExceptionsTest(unittest.TestCase):
    def test_seeded_load_batch_with_single_propagated_error(self) -> None:
        seed = 8813
        batch_size = 32
        specs = _build_version_specs(seed, batch_size)
        fail_index = _failure_slot(seed, batch_size)
        failure_value = _failure_non_string(seed)

        load.cache_clear()

        tables: list = []
        for index, spec in enumerate(specs):
            if index == fail_index:
                with self.assertRaises(Exception):
                    load(failure_value)
                continue

            if spec == "auto" and index % 4 == 0:
                os.environ["UNICODE_VERSION"] = _invalid_env_version(seed, index)
            else:
                os.environ.pop("UNICODE_VERSION", None)

            tables.append(load(spec))

        self.assertEqual(len(tables), batch_size - 1)
        self.assertGreater(len({table.unicode_version for table in tables}), 2)
        self.assertGreater(_table_fingerprint(tables), 12000)
