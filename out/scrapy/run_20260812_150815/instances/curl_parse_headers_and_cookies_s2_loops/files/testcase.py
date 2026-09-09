import random
import shlex
import unittest

from scrapy.utils.curl import curl_to_request_kwargs


class TestGeneratedCurlCookies(unittest.TestCase):
    def test_generated_headers_and_cookie_options(self):
        rng = random.Random(8675309)
        tokens = ["curl", "generated.example/items"]
        cookie_header_count = 0

        for index in range(47):
            if (rng.randrange(13) + index * index) % 5:
                pair_count = 1 + (rng.randrange(17) + index) % 4
                pairs = []
                for offset in range(pair_count):
                    key = f"h{(index * 11 + offset * 7) % 97}_{offset}"
                    value = f"v{rng.randrange(1000, 9999)}"
                    pairs.append(f"{key}={value}")
                header = f"cOoKiE: {'; '.join(pairs)}"
                cookie_header_count += 1
            else:
                header = f"X-Generated-{index}: {rng.randrange(10000, 99999)}"
            tokens.extend(["-H", header])

        for index in range(29):
            if (index + rng.randrange(9)) % 4 == 0:
                cookie_option = f"not-a-cookie-file-{index}"
            else:
                cookie_option = (
                    f"o{index}={rng.randrange(100, 999)}; "
                    f"shared{index % 7}={rng.randrange(1000, 9999)}"
                )
            tokens.extend(["-b", cookie_option])

        tokens.extend(["-u", "generated-user:generated-password"])
        curl_command = " ".join(shlex.quote(token) for token in tokens)
        kwargs = curl_to_request_kwargs(curl_command)

        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["url"], "http://generated.example/items")
        self.assertGreater(cookie_header_count, 20)
        self.assertGreater(len(kwargs["cookies"]), cookie_header_count)
        self.assertTrue(
            any(name == "Authorization" for name, _value in kwargs["headers"])
        )
