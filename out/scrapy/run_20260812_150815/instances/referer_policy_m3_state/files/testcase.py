import random
import unittest
import warnings

from scrapy.http import Request, Response
from scrapy.settings import Settings
from scrapy.spidermiddlewares.referer import RefererMiddleware


class RefererPolicyStateTest(unittest.TestCase):
    def setUp(self) -> None:
        baseline = RefererMiddleware(Settings())
        base_policy = baseline.policies[sorted(baseline.policies)[0]]
        custom_aliases = {}
        for index in range(9):
            token = ((index + 7) * 104729) ^ ((index + 19) * 8191)
            class_name = f"Generated{token:x}Policy"
            alias = f"generated-{(token * 31337 + index):x}"
            custom_aliases[alias] = type(
                class_name,
                (base_policy,),
                {"__module__": __name__},
            )
        self.middleware = RefererMiddleware(
            Settings({"REFERRER_POLICIES": custom_aliases})
        )
        self.policy_names = sorted(self.middleware.policies)

    def _exercise(self, specifications: list[tuple[str, str, str]], salt: int) -> None:
        signature = 0
        referer_headers = 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for index, (source, selected, decoy) in enumerate(specifications):
                origin_code = (salt * 65537 + index * 8191 + len(selected) * 257) % 104729
                target_code = (origin_code * 31337 + salt + index) % 130363
                response = Response(
                    f"https://origin-{origin_code:x}.invalid/path/{index:x}",
                    headers=(
                        {"Referrer-Policy": selected.encode("latin1")}
                        if source == "header"
                        else {"Referrer-Policy": decoy.encode("latin1")}
                    ),
                )
                meta = {"referrer_policy": selected} if source == "meta" else {}
                request = Request(
                    f"https://target-{target_code:x}.invalid/item/{salt:x}/{index:x}",
                    meta=meta,
                )
                processed = self.middleware.get_processed_request(request, response)
                self.assertIs(processed, request)
                referer_headers += b"Referer" in request.headers
                signature ^= (
                    (len(request.headers) + 1) * (index + 3)
                    + len(type(processed).__name__) * (salt + 5)
                    + target_code
                )

        self.assertGreater(len(specifications), 14)
        self.assertGreaterEqual(referer_headers, 0)
        self.assertNotEqual(signature, 0)

    def test_meta_policy_cycle(self) -> None:
        specs = [
            ("meta", self.policy_names[index % len(self.policy_names)], "ignored")
            for index in range(23)
        ]
        self._exercise(specs, 11)

    def test_meta_policy_reverse_stride(self) -> None:
        names = list(reversed(self.policy_names))
        specs = [
            ("meta", names[(index * 3 + 1) % len(names)], f"decoy-{index:x}")
            for index in range(19)
        ]
        self._exercise(specs, 17)

    def test_header_policy_cycle(self) -> None:
        specs = [
            ("header", self.policy_names[(index * 7) % len(self.policy_names)], "unused")
            for index in range(29)
        ]
        self._exercise(specs, 23)

    def test_header_case_variants(self) -> None:
        transforms = (str.upper, str.lower, str.swapcase, str.title)
        specs = [
            (
                "header",
                transforms[index % len(transforms)](
                    self.policy_names[(index * 5 + 2) % len(self.policy_names)]
                ),
                "unused",
            )
            for index in range(31)
        ]
        self._exercise(specs, 29)

    def test_meta_comma_lists(self) -> None:
        specs = []
        for index in range(21):
            first = self.policy_names[(index * 2) % len(self.policy_names)]
            last = self.policy_names[(index * 7 + 3) % len(self.policy_names)]
            invalid = f"unknown-{(index * 7919 + 97):x}"
            specs.append(("meta", ", ".join((first, invalid, last)), "unused"))
        self._exercise(specs, 31)

    def test_header_comma_lists_with_noise(self) -> None:
        specs = []
        for index in range(27):
            valid = self.policy_names[(index * 3 + 4) % len(self.policy_names)]
            noise = [
                f"noise-{(index * factor + 41):x}" for factor in (101, 211, 307)
            ]
            insert_at = (index * 5 + 1) % (len(noise) + 1)
            noise.insert(insert_at, valid)
            specs.append(("header", ",".join(noise), "unused"))
        self._exercise(specs, 37)

    def test_invalid_meta_fallbacks(self) -> None:
        specs = [
            (
                "meta",
                f"invalid-{((index + 13) * 104729 ^ (index << 9)):x}",
                self.policy_names[index % len(self.policy_names)],
            )
            for index in range(25)
        ]
        self._exercise(specs, 41)

    def test_invalid_header_fallbacks(self) -> None:
        specs = [
            (
                "header",
                ",".join(
                    f"bad-{(index * multiplier + 73):x}"
                    for multiplier in (409, 601, 809)
                ),
                "unused",
            )
            for index in range(17)
        ]
        self._exercise(specs, 43)

    def test_meta_precedes_header(self) -> None:
        specs = [
            (
                "meta",
                self.policy_names[(index * 7 + 5) % len(self.policy_names)],
                self.policy_names[(index * 3 + 2) % len(self.policy_names)],
            )
            for index in range(33)
        ]
        self._exercise(specs, 47)

    def test_empty_alias_interleaving(self) -> None:
        specs = []
        for index in range(22):
            chosen = (
                self.policy_names[0]
                if index % 3
                else self.policy_names[(index * 11 + 1) % len(self.policy_names)]
            )
            specs.append(("header" if index & 1 else "meta", chosen, "unused"))
        self._exercise(specs, 53)

    def test_seeded_policy_shuffle(self) -> None:
        generator = random.Random(0x51A7E)
        specs = []
        for index in range(35):
            selected = generator.choice(self.policy_names)
            source = generator.choice(("header", "meta"))
            decoy = generator.choice(self.policy_names)
            if generator.getrandbits(1):
                selected = f"junk-{generator.getrandbits(24):x},{selected}"
            specs.append((source, selected, decoy))
        self._exercise(specs, 59)

    def test_meta_import_paths(self) -> None:
        classes = sorted(
            {
                policy_class
                for policy_class in self.middleware.policies.values()
                if policy_class.__module__.startswith("scrapy.")
            },
            key=lambda policy_class: (policy_class.__module__, policy_class.__qualname__),
        )
        specs = []
        for index in range(24):
            policy_class = classes[(index * 5 + 1) % len(classes)]
            import_path = f"{policy_class.__module__}.{policy_class.__qualname__}"
            specs.append(("meta", import_path, f"unused-{index:x}"))
        self._exercise(specs, 61)
