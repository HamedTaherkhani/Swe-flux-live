import importlib.util
import json
import random
import sys
from types import SimpleNamespace
import types
import unittest
from unittest import mock

if importlib.util.find_spec("github") is None:
    github_stub = types.ModuleType("github")
    github_stub.Github = object
    sys.modules["github"] = github_stub

from scripts import notify_translations


class TestGeneratedTranslationNotifications(unittest.TestCase):
    def test_generated_discussion_matrix(self) -> None:
        seed_text = "translation-discussion-matrix"
        seed = sum(
            (position + 1) * ord(character)
            for position, character in enumerate(seed_text)
        )
        generator = random.Random(seed)

        language_count = 18 + generator.randrange(7)
        languages = [
            f"x{index:02d}{generator.randrange(1000, 10000):04d}"
            for index in range(language_count)
        ]

        pull_number = sum(ord(character) for character in seed_text) % 700 + 200
        login = f"reviewer-{seed % 997}"
        pull_labels = [
            SimpleNamespace(name=f"lang-{language}") for language in languages
        ]
        pull_labels.extend(
            [
                SimpleNamespace(name=notify_translations.lang_all_label),
                SimpleNamespace(name=notify_translations.awaiting_label),
                SimpleNamespace(name=f"triage-{seed % 31}"),
            ]
        )
        generator.shuffle(pull_labels)
        pull_request = SimpleNamespace(
            number=pull_number,
            user=SimpleNamespace(login=login),
            state="open",
            get_labels=lambda: list(pull_labels),
        )
        repository = SimpleNamespace(get_pull=lambda number: pull_request)
        github_client = SimpleNamespace(get_repo=lambda repository_name: repository)

        discussions = []
        discussion_total = language_count + 9 + generator.randrange(8)
        for discussion_index in range(discussion_total):
            edge_count = 2 + generator.randrange(7)
            edge_names = [
                f"topic-{discussion_index:02d}-{edge_index:02d}-"
                f"{generator.randrange(10000):04d}"
                for edge_index in range(edge_count)
            ]
            if discussion_index < language_count:
                replacement_index = generator.randrange(edge_count)
                edge_names[replacement_index] = f"lang-{languages[discussion_index]}"
            edges = [
                SimpleNamespace(node=SimpleNamespace(name=name)) for name in edge_names
            ]
            discussions.append(
                SimpleNamespace(
                    title=f"Discussion {discussion_index}",
                    id=f"discussion-{discussion_index}-{generator.randrange(100000)}",
                    number=1000 + discussion_index * 13 + generator.randrange(11),
                    labels=SimpleNamespace(edges=edges),
                )
            )

        new_message = (
            "Good news everyone! 😉 There's a new translation PR to be reviewed: "
            f"#{pull_number} by @{login}. 🎉 This requires 2 approvals from native "
            "speakers to be merged. 🤓"
        )
        done_message = (
            "~There's a new translation PR to be reviewed: "
            f"#{pull_number} by @{login}~ Good job! This is done. 🍰☕"
        )
        comment_batches = {}
        for language_index, discussion in enumerate(discussions[:language_count]):
            comments = []
            batch_size = 16 + generator.randrange(10)
            notified_slot = generator.randrange(batch_size)
            done_slot = generator.randrange(batch_size)
            for comment_index in range(batch_size):
                body = (
                    f"Review note {language_index}-{comment_index}: "
                    f"{generator.randrange(1_000_000)}"
                )
                if language_index % 4 == 1 and comment_index == notified_slot:
                    body = f"{body}\n{new_message}"
                elif language_index % 6 == 2 and comment_index == done_slot:
                    body = f"{body}\n{done_message}"
                comments.append(
                    notify_translations.Comment(
                        id=f"comment-{language_index}-{comment_index}",
                        url=f"https://example.invalid/{language_index}/{comment_index}",
                        body=body,
                    )
                )
            comment_batches[discussion.number] = comments

        event_payload = json.dumps({"pull_request": {"number": pull_number}})
        event_path = SimpleNamespace(
            is_file=lambda: True,
            read_text=lambda encoding: event_payload,
        )
        secret = SimpleNamespace(get_secret_value=lambda: "generated-token")
        settings = SimpleNamespace(
            debug=False,
            github_repository="generated/repository",
            github_token=secret,
            github_event_path=event_path,
            model_dump_json=lambda: "{}",
        )

        def make_comment(**kwargs):
            body = kwargs["body"]
            checksum = sum(map(ord, body)) % 100003
            return notify_translations.Comment(
                id=f"created-{checksum}",
                url=f"https://example.invalid/created/{checksum}",
                body=body,
            )

        with (
            mock.patch.object(notify_translations, "Settings", return_value=settings),
            mock.patch.object(
                notify_translations, "Github", return_value=github_client
            ),
            mock.patch.object(notify_translations.random, "random", return_value=0.0),
            mock.patch.object(notify_translations.time, "sleep") as sleep_mock,
            mock.patch.object(
                notify_translations,
                "get_graphql_translation_discussions",
                return_value=discussions,
            ),
            mock.patch.object(
                notify_translations,
                "get_graphql_translation_discussion_comments",
                side_effect=lambda **kwargs: list(
                    comment_batches[kwargs["discussion_number"]]
                ),
            ) as comments_mock,
            mock.patch.object(
                notify_translations, "create_comment", side_effect=make_comment
            ) as create_mock,
        ):
            notify_translations.main()

        sleep_mock.assert_called_once()
        self.assertEqual(comments_mock.call_count, len(languages))
        self.assertGreater(create_mock.call_count, 0)
        self.assertLess(create_mock.call_count, len(languages))
