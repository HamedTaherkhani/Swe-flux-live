from __future__ import annotations

import hashlib
import random
import unittest
from unittest import mock

from scrapy import cmdline
from scrapy.commands import ScrapyCommand
from scrapy.settings import Settings
from scrapy.utils.reactor import _asyncio_reactor_path


class RecordingCommand(ScrapyCommand):
    default_settings = {"LOG_ENABLED": False}

    def __init__(self, requires_process: bool):
        super().__init__()
        self.requires_crawler_process = requires_process
        self.seen = []

    def short_desc(self):
        return "generated command"

    def run(self, args, opts):
        digest = hashlib.blake2s(
            ("|".join(args) + repr(sorted(vars(opts)))).encode(), digest_size=8
        ).hexdigest()
        self.seen.append(digest)


class CmdlineExecuteDataFlowTest(unittest.TestCase):
    def test_generated_execute_schedule(self):
        rng = random.Random(5_104_729)
        schedule = [index % 4 for index in range(28)]
        rng.shuffle(schedule)
        plain = RecordingCommand(False)
        crawling = RecordingCommand(True)
        commands = {"plain": plain, "crawl": crawling}
        exits = []
        async_processes = []
        regular_processes = []

        def make_settings(ordinal):
            settings = Settings()
            selector = (rng.getrandbits(16) ^ ordinal) % 3
            settings.set(
                "TWISTED_REACTOR",
                _asyncio_reactor_path if selector == 0 else "twisted.internet.selectreactor.SelectReactor",
            )
            settings.set("TWISTED_REACTOR_ENABLED", selector != 1)
            settings.set("FORCE_CRAWLER_PROCESS", selector == 2 and ordinal % 5 == 0)
            return settings

        with (
            mock.patch.object(cmdline, "_get_commands_dict", return_value=commands),
            mock.patch.object(cmdline, "inside_project", side_effect=lambda: bool(rng.getrandbits(1))),
            mock.patch.object(cmdline, "_print_commands"),
            mock.patch.object(cmdline, "_print_unknown_command"),
            mock.patch.object(
                cmdline,
                "AsyncCrawlerProcess",
                side_effect=lambda settings: async_processes.append(settings) or object(),
            ),
            mock.patch.object(
                cmdline,
                "CrawlerProcess",
                side_effect=lambda settings: regular_processes.append(settings) or object(),
            ),
        ):
            for ordinal, mode in enumerate(schedule):
                token = hashlib.sha256(
                    f"{ordinal}:{rng.getrandbits(96)}".encode()
                ).hexdigest()
                if mode == 0:
                    argv = ["scrapy", "--nolog", f"--marker={token[:9]}"]
                elif mode == 1:
                    argv = ["scrapy", f"missing-{token[:11]}", token[11:23]]
                else:
                    command_name = "plain" if mode == 2 else "crawl"
                    argv = [
                        "scrapy",
                        "--nolog",
                        command_name,
                        token[3:17],
                        token[19:31],
                    ]

                supplied_settings = make_settings(ordinal)
                use_implicit_argv = (ordinal + mode) % 6 == 0
                use_implicit_settings = (ordinal * 3 + mode) % 7 == 0
                if use_implicit_argv:
                    cmdline.sys.argv = argv
                if use_implicit_settings:
                    generated = make_settings(ordinal ^ len(token))
                    settings_patch = mock.patch.object(
                        cmdline, "get_project_settings", return_value=generated
                    )
                else:
                    settings_patch = mock.patch.object(
                        cmdline, "get_project_settings", side_effect=AssertionError
                    )

                editor_patch = (
                    mock.patch.dict(cmdline.os.environ, {"EDITOR": token[-13:]})
                    if ordinal % 3
                    else mock.patch.dict(cmdline.os.environ, {}, clear=True)
                )
                with settings_patch, editor_patch:
                    with self.assertRaises(SystemExit) as raised:
                        cmdline.execute(
                            None if use_implicit_argv else argv,
                            None if use_implicit_settings else supplied_settings,
                        )
                exits.append(raised.exception.code)

        self.assertEqual(len(exits), len(schedule))
        self.assertEqual(set(exits), {0, 2})
        self.assertTrue(plain.seen and crawling.seen)
        self.assertTrue(async_processes)
        self.assertTrue(regular_processes)
