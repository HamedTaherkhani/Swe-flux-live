from __future__ import annotations

import random
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

github_stub = ModuleType("github")
github_stub.Github = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("github", github_stub)

import scripts.sponsors as sponsors


class TestSponsorsProgramState(unittest.TestCase):
    def test_main_collects_generated_sponsor_pages(self) -> None:
        rng = random.Random(20260811)
        pages: dict[str | None, list[dict[str, object]]] = {}
        after: str | None = None

        for page_index in range(5):
            page: list[dict[str, object]] = []
            for item_index in range(4):
                token = "".join(rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(9))
                cursor = f"cursor-{page_index}-{item_index}-{token[:4]}"
                price = float(5 + ((rng.randrange(1, 23) * (page_index + 3)) % 47))
                page.append(
                    {
                        "cursor": cursor,
                        "node": {
                            "sponsorEntity": {
                                "login": f"user-{token}",
                                "avatarUrl": f"https://images.invalid/{token}.png",
                                "url": f"https://profiles.invalid/{token[::-1]}",
                            },
                            "tier": {
                                "name": f"generated-tier-{int(price)}",
                                "monthlyPriceInDollars": price,
                            },
                        },
                    }
                )
            pages[after] = page
            after = str(page[-1]["cursor"])
        pages[after] = []

        class StubResponse:
            status_code = 200
            text = "generated response"

            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def json(self) -> dict[str, object]:
                return self._payload

        seen_after: list[str | None] = []

        def fake_post(*args: object, **kwargs: object) -> StubResponse:
            request_json = kwargs["json"]
            assert isinstance(request_json, dict)
            variables = request_json["variables"]
            assert isinstance(variables, dict)
            current_after = variables["after"]
            assert current_after is None or isinstance(current_after, str)
            seen_after.append(current_after)
            edges = pages[current_after]
            return StubResponse(
                {
                    "data": {
                        "user": {
                            "sponsorshipsAsMaintainer": {
                                "edges": edges,
                            }
                        }
                    }
                }
            )

        runtime_settings = SimpleNamespace(
            sponsors_token=SecretStr("runtime-sponsor-token"),
            github_token=SecretStr("runtime-github-token"),
            github_repository="generated/fastapi",
            httpx_timeout=17,
            model_dump_json=lambda: '{"settings":"generated"}',
        )
        repository = MagicMock()
        github = MagicMock()
        github.get_repo.return_value = repository

        with (
            patch.object(sponsors, "Settings", return_value=runtime_settings),
            patch.object(sponsors, "Github", return_value=github),
            patch.object(sponsors.httpx, "post", side_effect=fake_post),
            patch.object(sponsors, "update_content", return_value=False) as update,
        ):
            sponsors.main()

        self.assertTrue(update.called)
        self.assertEqual(seen_after[0], None)
        self.assertEqual(len(seen_after), len(pages))
        self.assertTrue(all(value is None or value.startswith("cursor-") for value in seen_after))
