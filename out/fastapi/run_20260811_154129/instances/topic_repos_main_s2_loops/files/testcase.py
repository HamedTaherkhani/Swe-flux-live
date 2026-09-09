import importlib.util
import random
import sys
import types
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest import mock


if importlib.util.find_spec("github") is None:
    github_stub = types.ModuleType("github")
    github_stub.Github = object
    sys.modules["github"] = github_stub

from scripts import topic_repos


@dataclass
class Owner:
    login: str
    html_url: str


@dataclass
class Candidate:
    full_name: str
    name: str
    html_url: str
    stargazers_count: int
    owner: Owner


class TestGeneratedTopicRepositories(unittest.TestCase):
    def test_seeded_repository_catalog(self) -> None:
        seed_text = "topic-repository-catalog"
        seed = sum(
            (position + 3) * ord(character)
            for position, character in enumerate(seed_text)
        )
        generator = random.Random(seed)
        repository_name = f"organization-{seed % 193}/project-{seed % 389}"
        candidate_total = sum((index % 7) + 1 for index in range(43))

        candidates = []
        for index in range(candidate_total):
            owner_token = generator.randrange(10_000, 1_000_000)
            repo_token = generator.randrange(10_000, 1_000_000)
            stars = (
                generator.randrange(50_000)
                + (owner_token % 211) * (index + 5)
                + repo_token % 97
            )
            full_name = f"owner-{owner_token}/repo-{index:03d}-{repo_token}"
            if (index * index + owner_token + repo_token) % 23 == 0:
                full_name = repository_name
            candidates.append(
                Candidate(
                    full_name=full_name,
                    name=f"repo-{index:03d}-{repo_token}",
                    html_url=f"https://example.invalid/repos/{owner_token}/{repo_token}",
                    stargazers_count=stars,
                    owner=Owner(
                        login=f"owner-{owner_token}",
                        html_url=f"https://example.invalid/owners/{owner_token}",
                    ),
                )
            )

        secret = SimpleNamespace(get_secret_value=lambda: f"token-{seed % 997}")
        settings = SimpleNamespace(
            github_repository=repository_name,
            github_token=secret,
            model_dump_json=lambda: f'{{"catalog_seed": {seed}}}',
        )
        selected_repository = SimpleNamespace()
        api = mock.Mock()
        api.get_repo.return_value = selected_repository
        api.search_repositories.return_value = iter(candidates)

        unchanged_document = f"catalog-{sum(item.stargazers_count for item in candidates) % 1_000_003}"
        path = mock.Mock()
        path.read_text.return_value = unchanged_document

        with (
            mock.patch.object(topic_repos, "Settings", return_value=settings),
            mock.patch.object(topic_repos, "Github", return_value=api),
            mock.patch.object(topic_repos, "Path", return_value=path),
            mock.patch.object(topic_repos.yaml, "dump", return_value=unchanged_document),
        ):
            result = topic_repos.main()

        self.assertIsNone(result)
        api.get_repo.assert_called_once_with(repository_name)
        api.search_repositories.assert_called_once_with(query="topic:fastapi")
        path.read_text.assert_called_once_with(encoding="utf-8")
        path.write_text.assert_not_called()
