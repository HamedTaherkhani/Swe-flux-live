import sys
import types
import unittest
from unittest import mock

from instructlab.model.backends import vllm


class TestStableVramControlFlow(unittest.TestCase):
    def test_middle_probe_survives_fluctuating_readings(self):
        class FakeCuda:
            def __init__(self):
                self.readings = iter(())
                self.fail_reads = False
                self.cache_attempts = 0

            def is_available(self):
                return True

            def device_count(self):
                return sum(1 for value in range(11) if value % 5 == 0)

            def mem_get_info(self, _device):
                if self.fail_reads:
                    raise RuntimeError("synthetic device telemetry failure")
                return next(self.readings), 0

            def empty_cache(self):
                self.cache_attempts += 1

        cuda = FakeCuda()
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = cuda
        fake_torch.device = lambda name: name

        totals = []
        current = sum((index + 3) ** 2 for index in range(13))
        for index in range(sum(1 for value in range(53) if value % 3 == 0)):
            if index and index % 3 == 2:
                current -= index % 5 + 1
            else:
                current += (index * index) % 17 + 2
            totals.append(current)

        device_count = cuda.device_count()
        cuda.readings = iter(
            part
            for total in totals
            for part in (
                total // device_count,
                total // device_count,
                total - 2 * (total // device_count),
            )
        )
        timeout = sum(value % 7 for value in totals) + len(totals)

        with (
            mock.patch.dict(sys.modules, {"torch": fake_torch}),
            mock.patch.object(vllm.time, "monotonic", return_value=0),
            mock.patch.object(vllm, "_sleep", return_value=None),
        ):
            vllm.wait_for_stable_vram(timeout - timeout)
            vllm.wait_for_stable_vram(timeout)
            cuda.fail_reads = True
            vllm.wait_for_stable_vram(timeout // len(totals))

        self.assertGreater(len(totals), 10)
        self.assertEqual(cuda.cache_attempts, 2)
        self.assertTrue(cuda.fail_reads)
