import random
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

if "github" not in sys.modules:
    github_module = types.ModuleType("github")
    github_module.Github = object
    sys.modules["github"] = github_module

import scripts.notify_translations as notifications


class GeneratedResponse:
    def __init__(self, mode: int) -> None:
        self.mode = mode

    @property
    def status_code(self) -> int:
        if self.mode == 5:
            return bytes([255]).decode("ascii")
        if self.mode in (1, 6):
            return 500 + self.mode
        return 200

    @property
    def text(self) -> str:
        if self.mode == 6:
            return {}[self.mode]
        return f"generated-response-{self.mode * self.mode + 17}"

    def json(self) -> dict:
        if self.mode == 2:
            return {"errors": [{"code": self.mode * 13 + 5}]}
        if self.mode == 4:
            return {"data": 1 // (self.mode - self.mode)}
        if self.mode == 7:
            return {"data": getattr(object(), "".join(chr(v) for v in (113, 97)))}
        if self.mode == 8:
            return {"data": sum([self.mode, "".join(chr(v) for v in (120,))])}
        if self.mode == 9:
            return {"data": chr(1 << (self.mode + 3))}
        if self.mode == 10:
            return {"data": iter(self.mode)}
        return {
            "data": {
                "repository": {
                    "discussions": {
                        "nodes": [],
                    }
                }
            }
        }


class TestGraphQLResponseFailures(unittest.TestCase):
    def test_generated_response_matrix(self) -> None:
        settings = notifications.Settings(
            github_repository="owner/repository",
            github_token="generated-token",
            github_event_path=Path.cwd() / "generated-event.json",
        )

        modes = list(range(11)) * 4
        random.Random(sum(index * index for index in range(19))).shuffle(modes)
        call_index = 0

        def generated_post(*_args, **_kwargs):
            nonlocal call_index
            mode = modes[call_index]
            call_index += 1
            if mode == 3:
                return [][call_index]
            return GeneratedResponse(mode)

        outcomes = []
        with mock.patch.object(notifications.httpx, "post", side_effect=generated_post):
            for _ in modes:
                try:
                    result = notifications.get_graphql_translation_discussions(
                        settings=settings
                    )
                except Exception:
                    outcomes.append(False)
                else:
                    outcomes.append(isinstance(result, list))

        self.assertEqual(call_index, len(modes))
        self.assertEqual(len(outcomes), len(modes))
        self.assertTrue(any(outcomes))
        self.assertFalse(all(outcomes))


if __name__ == "__main__":
    unittest.main()
