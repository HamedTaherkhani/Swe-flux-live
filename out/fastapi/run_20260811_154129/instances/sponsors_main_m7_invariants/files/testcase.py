import random
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

github_stub = ModuleType("github")
github_stub.Github = object
sys.modules.setdefault("github", github_stub)

from scripts import sponsors as sponsors_module


class TestSponsorsMainInvariants(unittest.TestCase):
    def test_seeded_tiers_reach_unchanged_content_exit(self) -> None:
        rng = random.Random(1023)
        draw_count = (
            len("runtime-sponsor-groups") + len("branches") + int(bool(rng))
        )
        tier_keys = {rng.randrange(25, 5000) for _ in range(draw_count)}

        tiers = {}
        for tier_index, key in enumerate(tier_keys):
            group_size = 3 + ((key ^ (tier_index * 17)) % 8)
            tiers[key] = {
                f"user-{tier_index:02d}-{member_index:02d}": (
                    sponsors_module.SponsorEntity(
                        login=f"user-{tier_index:02d}-{member_index:02d}",
                        avatarUrl=(
                            f"https://images.invalid/{key:x}/{member_index:x}.png"
                        ),
                        url=f"https://profiles.invalid/{key ^ member_index:x}",
                    )
                )
                for member_index in range(group_size)
            }

        fake_settings = SimpleNamespace(
            github_token=SecretStr("deterministic-token"),
            github_repository="example/fastapi-runtime",
            model_dump_json=lambda: '{"mode":"deterministic"}',
        )
        fake_repo = MagicMock()
        fake_github = MagicMock()
        fake_github.get_repo.return_value = fake_repo

        with (
            patch.object(sponsors_module, "Settings", return_value=fake_settings),
            patch.object(sponsors_module, "Github", return_value=fake_github),
            patch.object(
                sponsors_module, "get_individual_sponsors", return_value=tiers
            ),
            patch.object(sponsors_module, "update_content", return_value=False) as update,
            patch.object(sponsors_module.subprocess, "run") as subprocess_run,
        ):
            result = sponsors_module.main()

        self.assertIsNone(result)
        update.assert_called_once()
        subprocess_run.assert_not_called()
