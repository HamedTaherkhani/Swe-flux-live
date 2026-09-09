import random
import unittest
from unittest import TextTestResult

from scrapy.contracts import Contract, ContractsManager
from scrapy.spiders import Spider


class _RuntimeContract(Contract):
    def __repr__(self):
        return f"{type(self).__name__}({self.args[0]})"

    def adjust_request_args(self, args):
        token = int(self.args[0])
        previous = args.get("url", "https://seed.invalid/root")
        folded = sum((index + 1) * ord(char) for index, char in enumerate(previous))
        args["url"] = (
            f"https://example.invalid/{type(self).__name__[1:].lower()}/"
            f"{(folded ^ (token * 131)) % 100003:x}/{token % 97}"
        )
        args["priority"] = (token * 17 + folded) % 211 - 105
        return args


class _Amber(_RuntimeContract):
    name = "amber"


class _Blue(_RuntimeContract):
    name = "blue"

    def pre_process(self, response):
        return None


class _Cyan(_RuntimeContract):
    name = "cyan"

    def post_process(self, output):
        return None


class _Dune(_RuntimeContract):
    name = "dune"

    def pre_process(self, response):
        return None

    def post_process(self, output):
        return None


class _Ember(_RuntimeContract):
    name = "ember"


class _Fault(_RuntimeContract):
    name = "fault"

    def adjust_request_args(self, args):
        token = int(self.args[0])
        raise RuntimeError(f"generated contract failure {token ^ 0x5A5A}")


_CONTRACTS = [_Amber, _Blue, _Cyan, _Dune, _Ember, _Fault]
_NORMAL_NAMES = tuple(contract.name for contract in _CONTRACTS[:-1])


def _make_callback(name, doc):
    def callback(_self, _response):
        return ()

    callback.__name__ = name
    callback.__doc__ = doc
    return callback


def _build_spider(seed, callback_count, base_contracts, variant):
    rng = random.Random(seed)
    attributes = {"name": f"generated-{seed}-{variant}"}
    expected_nonempty = 0
    expected_errors = 0

    for callback_index in range(callback_count):
        count = base_contracts + callback_index * (1 + variant % 3)
        rows = []
        for position in range(count):
            name = _NORMAL_NAMES[
                (rng.randrange(len(_NORMAL_NAMES)) + position + variant)
                % len(_NORMAL_NAMES)
            ]
            token = (
                rng.randrange(41, 9001)
                + seed * (position + 3)
                + callback_index * 97
                + variant * variant
            )
            rows.append(f"@{name} {token}")

        if variant % 5 == 2 and callback_index == callback_count - 1:
            insertion = 1 + rng.randrange(max(1, len(rows) - 2))
            rows.insert(insertion, f"@fault {rng.randrange(101, 9901)}")
            expected_errors += 1
        else:
            expected_nonempty += 1

        method = _make_callback(
            f"parse_{callback_index:02d}_{variant:02d}", "\n".join(rows)
        )
        attributes[method.__name__] = method

    if variant % 4 == 3:
        empty_method = _make_callback(
            f"parse_empty_{variant:02d}", "@ !!! generated non-contract marker"
        )
        attributes[empty_method.__name__] = empty_method

    spider_class = type(f"GeneratedSpider{seed}_{variant}", (Spider,), attributes)
    return spider_class(), expected_nonempty, expected_errors


class TestContractsFromMethodInvariants(unittest.TestCase):
    def _exercise(self, seed, callback_count, base_contracts, variant):
        spider, expected_nonempty, expected_errors = _build_spider(
            seed, callback_count, base_contracts, variant
        )
        manager = ContractsManager(_CONTRACTS)
        results = TextTestResult(stream=None, descriptions=False, verbosity=0)

        requests = manager.from_spider(spider, results)

        self.assertEqual(sum(request is not None for request in requests), expected_nonempty)
        self.assertEqual(len(results.errors), expected_errors)
        self.assertFalse(results.failures)
        self.assertTrue(
            all(
                request is None
                or (
                    request.dont_filter
                    and request.callback is not None
                    and request.errback is not None
                )
                for request in requests
            )
        )

    def test_01_single_dense(self):
        self._exercise(137, 1, 19, 0)

    def test_02_pair_shifted(self):
        self._exercise(283, 2, 17, 1)

    def test_03_fault_late(self):
        self._exercise(419, 2, 21, 2)

    def test_04_empty_tail(self):
        self._exercise(557, 1, 23, 3)

    def test_05_triple_wave(self):
        self._exercise(691, 3, 16, 4)

    def test_06_long_single(self):
        self._exercise(827, 1, 31, 5)

    def test_07_pair_wide(self):
        self._exercise(953, 2, 24, 6)

    def test_08_fault_and_empty(self):
        self._exercise(1091, 3, 18, 7)

    def test_09_compact_triple(self):
        self._exercise(1229, 3, 15, 8)

    def test_10_deep_pair(self):
        self._exercise(1367, 2, 29, 9)

    def test_11_varied_quad(self):
        self._exercise(1499, 4, 17, 10)

    def test_12_final_fault(self):
        self._exercise(1637, 2, 27, 12)
