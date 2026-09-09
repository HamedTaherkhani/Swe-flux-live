from __future__ import annotations

import hashlib
import random
import unittest

from scrapy.exceptions import UsageError
from scrapy.settings import Settings
from scrapy.utils.conf import feed_process_params_from_cli


class FeedProcessParamsDataFlowTest(unittest.TestCase):
    @staticmethod
    def _tokens(seed: int, size: int) -> list[str]:
        rng = random.Random(seed)
        return [
            hashlib.blake2s(
                f"{index}:{rng.getrandbits(96)}".encode(), digest_size=9
            ).hexdigest()
            for index in range(size)
        ]

    @staticmethod
    def _settings(extra_feeds: dict[str, dict[str, object]] | None = None) -> Settings:
        return Settings({"FEEDS": extra_feeds or {}})

    def test_implicit_extension_rotation(self):
        tokens = self._tokens(77123, 27)
        formats = ("json", "xml", "csv", "jl")
        output = [
            f"exports/{token}.{formats[(index * index + 3) % len(formats)]}"
            for index, token in enumerate(tokens)
        ]
        result = feed_process_params_from_cli(self._settings(), output)
        self.assertEqual(len(result), len(set(output)))
        self.assertTrue(all("format" in config for config in result.values()))

    def test_explicit_format_permutation(self):
        tokens = self._tokens(91207, 31)
        formats = ("pickle", "json", "marshal", "csv", "xml")
        output = [
            f"bucket/{token}:{formats[(index * 7 + len(token)) % len(formats)]}"
            for index, token in enumerate(tokens)
        ]
        result = feed_process_params_from_cli(self._settings(), output)
        self.assertEqual(set(result), {entry.rsplit(":", 1)[0] for entry in output})
        self.assertFalse(any(config.get("overwrite") for config in result.values()))

    def test_mixed_implicit_and_explicit(self):
        tokens = self._tokens(50177, 34)
        formats = ("json", "xml", "csv")
        output = []
        for index, token in enumerate(tokens):
            selected = formats[(index + int(token[-1], 16)) % len(formats)]
            if (index ^ int(token[0], 16)) % 3:
                output.append(f"mixed/{token}.{selected}")
            else:
                output.append(f"mixed/{token}.data:{selected}")
        result = feed_process_params_from_cli(self._settings(), output)
        self.assertEqual(len(result), len(tokens))
        self.assertEqual({value["format"] for value in result.values()}, set(formats))

    def test_stdout_interleaved_with_uris(self):
        tokens = self._tokens(64091, 29)
        formats = ("json", "pickle", "xml", "jl")
        output = [
            (
                f"-:{formats[index % len(formats)]}"
                if (index + int(token[2], 16)) % 6 == 0
                else f"stream/{token}:{formats[(index * 3) % len(formats)]}"
            )
            for index, token in enumerate(tokens)
        ]
        result = feed_process_params_from_cli(self._settings(), output)
        self.assertLessEqual(len(result), len(output))
        self.assertTrue(result)

    def test_overwrite_implicit_outputs(self):
        tokens = self._tokens(83003, 24)
        formats = ("json", "csv", "xml")
        overwrite_output = [
            f"overwrite/{token}.{formats[(index * 5 + 1) % len(formats)]}"
            for index, token in enumerate(tokens)
        ]
        result = feed_process_params_from_cli(
            self._settings(), [], overwrite_output=overwrite_output
        )
        self.assertEqual(len(result), len(overwrite_output))
        self.assertTrue(all(value.get("overwrite") is True for value in result.values()))

    def test_overwrite_explicit_and_stdout(self):
        tokens = self._tokens(44201, 33)
        formats = ("jl", "json", "pickle", "csv")
        overwrite_output = []
        for index, token in enumerate(tokens):
            selected = formats[(int(token[3], 16) + index) % len(formats)]
            overwrite_output.append(
                f"-:{selected}"
                if index % 8 == 3
                else f"replace/{token}.blob:{selected}"
            )
        result = feed_process_params_from_cli(
            self._settings(), [], overwrite_output=overwrite_output
        )
        self.assertTrue(result)
        self.assertTrue(all(value["overwrite"] for value in result.values()))

    def test_colon_fallback_to_file_suffix(self):
        tokens = self._tokens(10937, 26)
        formats = ("json", "xml", "csv", "jl")
        output = [
            f"scheme{index % 5}:nested/{token}.{formats[int(token[-2], 16) % 4]}"
            for index, token in enumerate(tokens)
        ]
        result = feed_process_params_from_cli(self._settings(), output)
        self.assertEqual(len(result), len(output))
        self.assertTrue(all("/" in uri for uri in result))

    def test_preconfigured_feeds_override_cli(self):
        tokens = self._tokens(38713, 22)
        formats = ("json", "xml", "csv")
        output = [
            f"merge/{token}.{formats[(index + 2) % len(formats)]}"
            for index, token in enumerate(tokens)
        ]
        overridden = output[len(tokens) // 3]
        extras = {
            overridden: {"format": "pickle", "encoding": "utf8"},
            f"preset/{tokens[-1]}": {"format": "jl"},
        }
        result = feed_process_params_from_cli(self._settings(extras), output)
        self.assertGreater(len(result), len(output))
        self.assertEqual(result[overridden], extras[overridden])

    def test_repeated_uri_redefinitions(self):
        tokens = self._tokens(27509, 36)
        formats = ("json", "xml", "csv", "pickle")
        output = [
            f"repeat/{tokens[index % 9]}.data:{formats[(index * 11) % len(formats)]}"
            for index in range(len(tokens))
        ]
        result = feed_process_params_from_cli(self._settings(), output)
        self.assertLess(len(result), len(output))
        self.assertEqual(set(result), {entry.rsplit(":", 1)[0] for entry in output})

    def test_empty_cli_with_generated_settings(self):
        tokens = self._tokens(71843, 19)
        formats = ("json", "xml", "jl")
        extras = {
            f"configured/{token}": {"format": formats[(index * 2) % len(formats)]}
            for index, token in enumerate(tokens)
        }
        result = feed_process_params_from_cli(self._settings(extras), [])
        self.assertEqual(result, extras)
        self.assertIsNot(result, extras)

    def test_conflicting_output_modes(self):
        tokens = self._tokens(96331, 21)
        normal = [f"normal/{token}.json" for token in tokens]
        replacement = [f"replacement/{token}.xml" for token in reversed(tokens)]
        with self.assertRaises(UsageError):
            feed_process_params_from_cli(
                self._settings(), normal, overwrite_output=replacement
            )

    def test_late_invalid_format_after_valid_prefix(self):
        tokens = self._tokens(15643, 25)
        formats = ("json", "xml", "csv", "jl")
        output = [
            f"prefix/{token}.{formats[(index * 3) % len(formats)]}"
            for index, token in enumerate(tokens)
        ]
        output.append(f"broken/{tokens[0]}.{tokens[-1]}")
        with self.assertRaises(UsageError):
            feed_process_params_from_cli(self._settings(), output)
