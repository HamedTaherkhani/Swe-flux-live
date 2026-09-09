import builtins
import random
import tempfile
import unittest
from unittest.mock import patch

from jinja2 import Environment
from jinja2.bccache import Bucket, FileSystemBytecodeCache


def _non_os_builtin_exceptions() -> tuple[type[BaseException], ...]:
    return tuple(
        getattr(builtins, name)
        for name in sorted(dir(builtins))
        if isinstance(getattr(builtins, name), type)
        and issubclass(getattr(builtins, name), BaseException)
        and not issubclass(getattr(builtins, name), OSError)
        and getattr(builtins, name).__module__ == "builtins"
        and name[0].isupper()
    )


_NON_OS_BUILTIN_EXCEPTIONS = _non_os_builtin_exceptions()


def _build_operations(seed: int, operation_count: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    return [(rng.randint(0, 4), index) for index in range(operation_count)]


def _make_bucket(env: Environment, key: str, checksum: str, with_code: bool) -> Bucket:
    bucket = Bucket(env, key, checksum)
    if with_code:
        bucket.code = compile(f"x = {checksum!r}", f"<{key}>", "exec")
    return bucket


class TestFileSystemBytecodeCacheDumpBytecode(unittest.TestCase):
    def test_dump_bytecode_caught_exception_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileSystemBytecodeCache(tmpdir)
            env = Environment()
            operations = _build_operations(seed=20240814, operation_count=32)
            checksum = 0
            failure_count = 0

            for variant, index in operations:
                key = f"slot_{index}_{variant}"
                checksum_tag = f"tag_{index * 9 + variant * 3}"
                with_code = variant != 1
                bucket = _make_bucket(env, key, checksum_tag, with_code=with_code)

                try:
                    if variant == 2:
                        with patch(
                            "os.replace",
                            side_effect=OSError(13, "blocked replace"),
                        ):
                            cache.dump_bytecode(bucket)
                    elif variant == 3:
                        exc_type = _NON_OS_BUILTIN_EXCEPTIONS[
                            index % len(_NON_OS_BUILTIN_EXCEPTIONS)
                        ]
                        with patch("os.replace", side_effect=exc_type()):
                            cache.dump_bytecode(bucket)
                    else:
                        cache.dump_bytecode(bucket)
                except BaseException:
                    failure_count += 1

                checksum ^= index * 17 + variant * 5 + len(key)

            self.assertEqual(checksum, 652)
            self.assertEqual(failure_count, 8)
