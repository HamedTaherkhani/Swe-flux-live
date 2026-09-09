import errno
import os
import random
import stat
import tempfile
import unittest
from unittest import mock

from jinja2.bccache import FileSystemBytecodeCache


def _collision_marker_name(seed: int) -> str:
    base = 65 + (seed % 26)
    return "".join(
        chr(base + ((index * 5 + seed) % 26))
        for index in range(10)
    )


def _build_schedule(length: int, rng: random.Random) -> list[int]:
    return [rng.randint(0, 4) for _ in range(length)]


class BccacheDefaultCacheDirS5ExceptionsTest(unittest.TestCase):
    def test_repeated_default_cache_dir_resolution(self) -> None:
        rng = random.Random(20260814)
        iterations = 20 + rng.randint(0, 11) + rng.randint(0, 7)
        schedule = _build_schedule(iterations * 2, rng)

        marker_name = _collision_marker_name(rng.randint(1, 10_000))
        collision_marker = type(
            marker_name,
            (OSError,),
            {"__module__": "testcase"},
        )

        cache = FileSystemBytecodeCache.__new__(FileSystemBytecodeCache)
        cache_root = os.path.join(
            tempfile.gettempdir(),
            f"_jinja2-cache-{os.getuid()}",
        )
        try:
            os.mkdir(cache_root, stat.S_IRWXU)
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise

        real_mkdir = os.mkdir
        real_chmod = os.chmod
        mkdir_counter = 0
        chmod_counter = 0

        def patched_mkdir(path: str, mode: int) -> None:
            nonlocal mkdir_counter
            mkdir_counter += 1
            tag = schedule[mkdir_counter % len(schedule)]
            if tag == 1:
                raise collision_marker(
                    errno.EEXIST,
                    f"x-{mkdir_counter}",
                    path,
                )
            return real_mkdir(path, mode)

        def patched_chmod(path: str, mode: int) -> None:
            nonlocal chmod_counter
            chmod_counter += 1
            tag = schedule[(chmod_counter + 3) % len(schedule)]
            if tag == 1:
                raise collision_marker(errno.EEXIST, f"y-{chmod_counter}")
            return real_chmod(path, mode)

        resolved_paths: list[str] = []
        with mock.patch("os.mkdir", side_effect=patched_mkdir), mock.patch(
            "os.chmod", side_effect=patched_chmod
        ):
            for _ in range(iterations):
                resolved_paths.append(cache._get_default_cache_dir())

        self.assertEqual(len(resolved_paths), iterations)
        self.assertTrue(all(isinstance(path, str) for path in resolved_paths))
        self.assertEqual(len(set(resolved_paths)), 1)
        self.assertTrue(os.path.isdir(resolved_paths[0]))
        self.assertGreater(iterations, 19)
        self.assertGreater(len(schedule), iterations)
