import random
import shlex
import unittest
import warnings

from scrapy.utils.curl import curl_to_request_kwargs


class CurlProgramStateTest(unittest.TestCase):
    def test_generated_curl_commands(self) -> None:
        generator = random.Random(0xC0A57A7E)
        branch_counts = {"body": 0, "cookies": 0, "headers": 0, "post": 0}
        signature = 0

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for index in range(56):
                raw = generator.getrandbits(63)
                host = f"node-{(raw >> 7) % 1009}.invalid"
                path_parts = [
                    f"{(raw >> shift) % 4093:x}" for shift in (3, 17, 31, 45)
                ]
                url = host + "/" + "/".join(path_parts)
                if raw & 1:
                    url = ("https" if raw & 2 else "http") + "://" + url

                tokens = ["curl", url]
                header_count = 1 + (raw % 4)
                for header_index in range(header_count):
                    header_value = (
                        raw ^ (index + 3) * (header_index + 5) * 0x45D9F3B
                    ) % 1000003
                    tokens.extend(
                        [
                            "-H",
                            f"X-Calc-{header_index}: {header_value:x}-{index:x}",
                        ]
                    )

                cookie_seed = (raw ^ (raw >> 23) ^ (index * 8191)) % 10000019
                tokens.extend(
                    [
                        "-H",
                        (
                            f"Cookie: session={cookie_seed:x}; "
                            f"lane={(cookie_seed * 7 + index) % 65537:x}"
                        ),
                        "-b",
                        (
                            f"session={(cookie_seed ^ 0x5A5A5A) % 999983:x}; "
                            f"token={(cookie_seed * 13 + raw) % 10000079:x}"
                        ),
                    ]
                )

                if raw % 5:
                    chunks = [
                        f"p{part_index}={(raw >> (part_index * 9)) % 8191:x}"
                        for part_index in range(1 + (raw % 3))
                    ]
                    for chunk in chunks:
                        tokens.extend(["--data-raw", chunk])

                if raw % 4 == 0:
                    verbs = ["delete", "patch", "put"]
                    tokens.extend(["-X", verbs[(raw >> 11) % len(verbs)]])
                if raw % 6 == 0:
                    tokens.extend(
                        [
                            "-u",
                            (
                                f"user{(raw >> 13) % 997}:"
                                f"pass{(raw ^ index) % 10007}"
                            ),
                        ]
                    )
                if raw % 7 == 0:
                    tokens.append(f"--mystery-{(raw >> 29) % 97}")

                result = curl_to_request_kwargs(shlex.join(tokens))
                branch_counts["body"] += "body" in result
                branch_counts["cookies"] += bool(result.get("cookies"))
                branch_counts["headers"] += bool(result.get("headers"))
                branch_counts["post"] += result["method"] == "POST"
                signature ^= (
                    len(result["url"]) * (index + 1)
                    + len(result.get("headers", ())) * 17
                    + len(result.get("cookies", {})) * 31
                    + len(result.get("body", "")) * 43
                )

        self.assertGreater(min(branch_counts.values()), len(branch_counts))
        self.assertTrue(signature)
