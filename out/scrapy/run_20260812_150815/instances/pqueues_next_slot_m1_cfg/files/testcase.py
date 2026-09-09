from __future__ import annotations

import random
import unittest
from unittest.mock import Mock

from scrapy import Request
from scrapy.core.downloader import Downloader
from scrapy.pqueues import DownloaderAwarePriorityQueue
from scrapy.spiders import Spider
from scrapy.squeues import FifoMemoryQueue
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.test import get_crawler
from tests.utils.downloader import MockDownloader


class PriorityQueueSelectionTest(unittest.TestCase):
    def exercise_scenario(
        self,
        *,
        seed: int,
        slot_count: int,
        active_modulus: int,
        stride: int,
        operations: str,
    ) -> None:
        rng = random.Random(seed)
        downloader = MockDownloader()
        crawler = get_crawler(Spider)
        crawler.engine = Mock(downloader=downloader)
        queue = build_from_crawler(
            DownloaderAwarePriorityQueue,
            crawler,
            downstream_queue_cls=FifoMemoryQueue,
            key="",
        )

        offset = rng.randrange(slot_count)
        slots = [
            f"bucket-{(index * stride + offset) % slot_count:02d}-"
            f"{chr(97 + (seed + index * 5) % 26)}"
            for index in range(slot_count)
        ]
        insertion_order = list(range(slot_count))
        rng.shuffle(insertion_order)
        active_counts = {
            slots[index]: (
                (index * stride + rng.randrange(active_modulus * 3 + 1))
                ^ (seed >> (index % 7))
            )
            % active_modulus
            for index in range(slot_count)
        }

        total_requests = 0
        for index in insertion_order:
            slot = slots[index]
            copies = 1 + ((seed + index * stride) % 3)
            for copy_index in range(copies):
                request = Request(
                    f"https://example.invalid/{seed:x}/{index:x}/{copy_index:x}",
                    meta={Downloader.DOWNLOAD_SLOT: slot},
                    priority=(index * active_modulus + copy_index) % 7,
                )
                queue.push(request)
                total_requests += 1
            for _ in range(active_counts[slot]):
                downloader.increment(slot)

        observed = []
        try:
            for operation in operations:
                request = queue.peek() if operation == "k" else queue.pop()
                self.assertIsNotNone(request)
                slot = request.meta[Downloader.DOWNLOAD_SLOT]
                self.assertIn(slot, active_counts)
                observed.append((operation, slot, request.priority))

            self.assertEqual(len(observed), len(operations))
            self.assertTrue(any(operation == "p" for operation, _, _ in observed))
            self.assertLess(len(queue), total_requests)
        finally:
            queue.close()

    def test_rotating_dense_ties(self):
        self.exercise_scenario(
            seed=730_021,
            slot_count=29,
            active_modulus=4,
            stride=11,
            operations="kppkpppk",
        )

    def test_sparse_scores_with_peeks(self):
        self.exercise_scenario(
            seed=481_937,
            slot_count=23,
            active_modulus=9,
            stride=7,
            operations="kkppkppp",
        )

    def test_reverse_lexical_pressure(self):
        self.exercise_scenario(
            seed=915_403,
            slot_count=31,
            active_modulus=5,
            stride=30,
            operations="pkpkppkp",
        )

    def test_prime_stride_rotation(self):
        self.exercise_scenario(
            seed=264_811,
            slot_count=37,
            active_modulus=6,
            stride=17,
            operations="ppkkpppkp",
        )

    def test_many_equal_minima(self):
        self.exercise_scenario(
            seed=608_159,
            slot_count=27,
            active_modulus=3,
            stride=8,
            operations="kpkppkpp",
        )

    def test_wide_score_distribution(self):
        self.exercise_scenario(
            seed=347_993,
            slot_count=34,
            active_modulus=12,
            stride=13,
            operations="ppkppkkp",
        )

    def test_smallest_supported_volume(self):
        self.exercise_scenario(
            seed=852_173,
            slot_count=17,
            active_modulus=7,
            stride=5,
            operations="kpppkpk",
        )

    def test_even_slot_permutation(self):
        self.exercise_scenario(
            seed=193_769,
            slot_count=32,
            active_modulus=8,
            stride=15,
            operations="pkppkkppp",
        )

    def test_clustered_active_counts(self):
        self.exercise_scenario(
            seed=779_447,
            slot_count=26,
            active_modulus=2,
            stride=9,
            operations="kkpppkpp",
        )

    def test_longer_selection_history(self):
        self.exercise_scenario(
            seed=526_123,
            slot_count=35,
            active_modulus=10,
            stride=12,
            operations="pkppkppkkpp",
        )

    def test_coprime_slot_walk(self):
        self.exercise_scenario(
            seed=401_627,
            slot_count=33,
            active_modulus=5,
            stride=19,
            operations="kppkkppp",
        )

    def test_high_tie_turnover(self):
        self.exercise_scenario(
            seed=968_251,
            slot_count=28,
            active_modulus=3,
            stride=23,
            operations="ppkpkppkp",
        )
