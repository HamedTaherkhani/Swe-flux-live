from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from kedro.config import OmegaConfigLoader


class TestGeneratedDuplicateState(unittest.TestCase):
    def test_catalog_pair_matrix(self) -> None:
        workspace = Path.cwd() / "data" / "repo_behave_omega_matrix_hard"
        shutil.rmtree(workspace, ignore_errors=True)
        config_dir = workspace / "generated"
        config_dir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, workspace, True)

        file_count = sum((ord(character) % 3) + 2 for character in "configuration")
        configs: list[dict[str, int]] = [dict() for _ in range(file_count)]
        rolling = sum(
            (position + 5) * ord(character)
            for position, character in enumerate("check_duplicates_state")
        )

        for left in range(file_count):
            for right in range(left + 1, file_count):
                rolling = (
                    rolling * 137 + (left + 3) * 101 + (right + 5) * 197
                ) % 1_000_003
                overlap_count = (rolling + left * 7 + right * 11) % 23 + 1
                for offset in range(overlap_count):
                    token = (
                        rolling * (offset + 17)
                        + left * 1009
                        + right * 2027
                        + offset * offset
                    ) % 1_000_003
                    key = f"feature_{left:x}_{right:x}_{offset:x}_{token:06x}"
                    configs[left][key] = token ^ (left << 8)
                    configs[right][key] = token ^ (right << 8)

                hidden = f"_internal_{(rolling ^ (left * right + 31)):x}"
                configs[left][hidden] = rolling + left
                configs[right][hidden] = rolling + right

        for index, config in enumerate(configs):
            path = config_dir / f"catalog_{index:02d}.json"
            path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")

        loader = OmegaConfigLoader(
            conf_source=workspace,
            base_env="generated",
            default_run_env="generated",
        )
        with self.assertRaises(ValueError) as raised:
            loader["catalog"]

        messages = str(raised.exception).splitlines()
        self.assertEqual(len(messages), file_count * (file_count - 1) // 2)
        self.assertTrue(all(message.startswith("Duplicate keys") for message in messages))
