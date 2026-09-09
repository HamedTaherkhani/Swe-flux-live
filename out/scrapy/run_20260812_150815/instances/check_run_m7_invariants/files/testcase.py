from __future__ import annotations

import argparse
import contextlib
import io
import random
import string
import unittest
from unittest.mock import patch

from scrapy.commands.check import Command
import scrapy.commands.check as check_module


class _Settings:
    def get_component_priority_dict_with_base(self, name):
        if not name.endswith("CONTRACTS"):
            raise AssertionError("unexpected setting lookup")
        return {}


class _SpiderLoader:
    def __init__(self, spiders):
        self._spiders = spiders
        self.loaded = []

    def list(self):
        return list(self._spiders)

    def load(self, name):
        self.loaded.append(name)
        return self._spiders[name]


class _CrawlerProcess:
    def __init__(self, spiders):
        self.spider_loader = _SpiderLoader(spiders)
        self.crawled = []
        self.starts = 0

    def crawl(self, spidercls):
        self.crawled.append(spidercls.name)

    def start(self):
        self.starts += 1


class _ContractsManager:
    def tested_methods_from_spidercls(self, spidercls):
        return list(spidercls.contract_methods)

    def from_spider(self, result):
        return ()


class CheckRunInvariantTests(unittest.TestCase):
    def _run_scenario(
        self,
        *,
        seed,
        size,
        list_mode,
        explicit_args,
        verbose,
        reverse_loader,
    ):
        rng = random.Random(seed)
        alphabet = string.ascii_lowercase
        spiders = {}
        names = []
        rolling = seed * 19 + size
        for index in range(size):
            rolling = (rolling * 73 + rng.randrange(1, 997) + index * 11) % 10007
            width = 5 + (rolling % 9)
            token = "".join(
                alphabet[(rolling + index * 7 + offset * offset * 3) % len(alphabet)]
                for offset in range(width)
            )
            name = f"{token}_{(rolling * (index + 3)) % 101}"
            score = sum((position + 1) * ord(char) for position, char in enumerate(name))
            method_count = (score + rolling + seed + index * index) % 9
            methods = [
                f"check_{(score * (slot + 5) + rolling) % 103}_{slot}"
                for slot in range(method_count)
            ]
            spidercls = type(
                f"GeneratedSpider_{seed}_{index}",
                (),
                {"name": name, "contract_methods": methods},
            )
            spiders[name] = spidercls
            names.append(name)

        loader_names = list(reversed(names)) if reverse_loader else names[::2] + names[1::2]
        ordered_spiders = {name: spiders[name] for name in loader_names}
        process = _CrawlerProcess(ordered_spiders)
        command = Command()
        command.settings = _Settings()
        command.crawler_process = process
        opts = argparse.Namespace(list=list_mode, verbose=verbose)
        args = list(names) if explicit_args else []
        manager = _ContractsManager()

        output = io.StringIO()
        with (
            patch.object(check_module, "build_component_list", return_value=[]),
            patch.object(check_module, "ContractsManager", return_value=manager),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            command.run(args, opts)

        self.assertEqual(len(process.spider_loader.loaded), len(names))
        self.assertEqual(process.starts, int(not list_mode))
        self.assertEqual(len(process.crawled) == 0, list_mode)
        self.assertIsInstance(output.getvalue(), str)

    def test_seeded_listing_explicit_forward(self):
        self._run_scenario(seed=31, size=23, list_mode=True, explicit_args=True, verbose=False, reverse_loader=False)

    def test_seeded_listing_loader_reverse(self):
        self._run_scenario(seed=47, size=19, list_mode=True, explicit_args=False, verbose=True, reverse_loader=True)

    def test_seeded_execution_explicit_reverse(self):
        self._run_scenario(seed=59, size=21, list_mode=False, explicit_args=True, verbose=False, reverse_loader=True)

    def test_seeded_execution_loader_interleaved(self):
        self._run_scenario(seed=71, size=25, list_mode=False, explicit_args=False, verbose=True, reverse_loader=False)

    def test_listing_wide_names(self):
        self._run_scenario(seed=83, size=18, list_mode=True, explicit_args=True, verbose=True, reverse_loader=True)

    def test_execution_wide_names(self):
        self._run_scenario(seed=97, size=27, list_mode=False, explicit_args=False, verbose=False, reverse_loader=False)

    def test_listing_alternate_order(self):
        self._run_scenario(seed=109, size=22, list_mode=True, explicit_args=False, verbose=False, reverse_loader=False)

    def test_execution_alternate_order(self):
        self._run_scenario(seed=127, size=20, list_mode=False, explicit_args=True, verbose=True, reverse_loader=False)

    def test_listing_dense_contracts(self):
        self._run_scenario(seed=149, size=26, list_mode=True, explicit_args=True, verbose=False, reverse_loader=True)

    def test_execution_dense_contracts(self):
        self._run_scenario(seed=163, size=24, list_mode=False, explicit_args=False, verbose=True, reverse_loader=True)

    def test_listing_final_mix(self):
        self._run_scenario(seed=181, size=17, list_mode=True, explicit_args=False, verbose=True, reverse_loader=True)

    def test_execution_final_mix(self):
        self._run_scenario(seed=197, size=28, list_mode=False, explicit_args=True, verbose=False, reverse_loader=False)
