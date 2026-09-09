import contextlib
import hashlib
import io
import random
import sys
from types import SimpleNamespace
import types
import unittest
from unittest.mock import patch


if "github" not in sys.modules:
    github_stub = types.ModuleType("github")

    class StubAuth:
        @staticmethod
        def Token(token):
            return ("token", token)

    github_stub.Auth = StubAuth
    github_stub.Github = object
    sys.modules["github"] = github_stub

from scripts import deploy_docs_status


class FakeCommit:
    def __init__(self, sha):
        self.sha = sha
        self.statuses = []

    def create_status(self, **kwargs):
        self.statuses.append(kwargs)


class FakeComment:
    def __init__(self, body, login):
        self.body = body
        self.user = SimpleNamespace(login=login)
        self.edits = []

    def edit(self, message):
        self.edits.append(message)


class FakeIssue:
    def __init__(self, comments):
        self.comments = comments
        self.created = []

    def get_comments(self):
        return iter(self.comments)

    def create_comment(self, message):
        self.created.append(message)


class FakePull:
    def __init__(self, sha, commits, files, issue):
        self.head = SimpleNamespace(sha=sha)
        self._commits = commits
        self._files = files
        self._issue = issue

    def get_commits(self):
        return iter(self._commits)

    def get_files(self):
        return iter(self._files)

    def as_issue(self):
        return self._issue


class FakeRepository:
    def __init__(self, pulls):
        self._pulls = pulls

    def get_pulls(self):
        return iter(self._pulls)


class FakeGithub:
    def __init__(self, repository):
        self._repository = repository

    def get_repo(self, name):
        if "/" not in name:
            raise AssertionError("repository name was not normalized")
        return self._repository


class GeneratedSettings:
    def __init__(self, repository, token, deploy_url, commit_sha, run_id):
        self.github_repository = repository
        self.github_token = deploy_docs_status.SecretStr(token)
        self.deploy_url = deploy_url
        self.commit_sha = commit_sha
        self.run_id = run_id
        self.state = "success"

    def model_dump_json(self):
        return '{"state":"success","generated":true}'


class TestDeployDocsStatusMain(unittest.TestCase):
    def test_builds_preview_state_from_generated_files(self):
        rng = random.Random(8_104_729)
        languages = ("en", "es", "de", "fr", "ja")
        sections = ("tutorial", "advanced", "reference", "how-to")
        generated_names = []
        for index in range(32):
            language = languages[(index * 7 + rng.randrange(len(languages))) % len(languages)]
            section = sections[(index * 3 + rng.randrange(len(sections))) % len(sections)]
            token = "".join(rng.choice("abcdefghjkmnpqrstuvwxyz") for _ in range(7))
            if index % 4 == 0:
                filename = f"docs/{language}/docs/{section}/{token}/index.md"
            else:
                filename = f"docs/{language}/docs/{section}/{token}_{index:02d}.md"
            generated_names.append(filename)
            if index % 6 == 0:
                generated_names.append(f"docs/assets/{token}_{index}.svg")
        generated_names.extend(f"src/generated_{i}.py" for i in range(5))
        rng.shuffle(generated_names)

        digest = hashlib.sha256("\n".join(generated_names).encode()).hexdigest()
        commit_sha = digest
        current_commit = FakeCommit(commit_sha)
        commits = [FakeCommit(hashlib.sha256(str(i).encode()).hexdigest()) for i in range(4)]
        commits.insert(rng.randrange(len(commits) + 1), current_commit)

        old_comment = FakeComment("unrelated generated note", "github-actions[bot]")
        preview_comment = FakeComment("## 📝 Docs preview\nstale generated body", "github-actions[bot]")
        issue = FakeIssue([old_comment, preview_comment])
        pull = FakePull(
            commit_sha,
            commits,
            [SimpleNamespace(filename=name) for name in generated_names],
            issue,
        )
        repository = FakeRepository(
            [
                FakePull(digest[::-1], [], [], FakeIssue([])),
                pull,
                FakePull(digest[::2], [], [], FakeIssue([])),
            ]
        )
        settings = GeneratedSettings(
            repository=f"generated/{digest[:9]}",
            token=digest[9:33],
            deploy_url=f"https://preview.example.test/{digest[33:49]}///",
            commit_sha=commit_sha,
            run_id=sum(ord(character) for character in digest[:20]),
        )

        output = io.StringIO()
        with (
            patch.object(deploy_docs_status, "Settings", return_value=settings),
            patch.object(
                deploy_docs_status,
                "Github",
                return_value=FakeGithub(repository),
            ),
            contextlib.redirect_stdout(output),
        ):
            result = deploy_docs_status.main()

        self.assertIsNone(result)
        self.assertEqual(len(current_commit.statuses), 1)
        self.assertFalse(issue.created)
        self.assertEqual(len(preview_comment.edits), 1)
        self.assertGreater(output.getvalue().count("\n"), len(languages))
