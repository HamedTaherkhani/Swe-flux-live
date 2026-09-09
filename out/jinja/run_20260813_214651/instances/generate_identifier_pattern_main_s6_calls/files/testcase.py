import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.generate_identifier_pattern as gid
from scripts.generate_identifier_pattern import main


def _unicode_scan_limits(seed: str, batch_count: int) -> list[int]:
    limits: list[int] = []
    for idx in range(batch_count):
        digest = hashlib.blake2b(
            f"{seed}:unicode_cap:{idx}".encode(), digest_size=4
        ).hexdigest()
        limits.append(1200 + (int(digest, 16) % 4800))
    return limits


class GenerateIdentifierPatternMainS6CallsTest(unittest.TestCase):
    def test_main_seeded_unicode_scan_batches(self) -> None:
        limits = _unicode_scan_limits("gid_main_s6", 12)
        payload_lengths: list[int] = []
        open_mock = mock_open()

        def _record_write(data: str) -> int:
            payload_lengths.append(len(data))
            return len(data)

        open_mock.return_value.write.side_effect = _record_write

        for cap in limits:
            with patch.object(gid.sys, "maxunicode", cap):
                with patch("builtins.open", open_mock):
                    main()

        self.assertEqual(len(payload_lengths), len(limits) * 6)
        self.assertGreater(sum(payload_lengths), 0)
        self.assertTrue(all(length > 0 for length in payload_lengths))
