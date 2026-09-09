import hashlib
import unittest

from jinja2.utils import urlize


def _token_for_slot(digest: str, slot: int) -> str:
    offset = (slot * 5) % (len(digest) - 2)
    byte = int(digest[offset : offset + 2], 16)
    kind = byte % 11
    tag = (byte >> 4) & 0x0F

    if kind == 0:
        return f"https://svc{tag}-{slot}.example.net/docs)"
    if kind == 1:
        return f"(www.hub{tag}-{slot}.org/guide.html,"
    if kind == 2:
        return f"ops{tag}{slot}@mail{slot}.corp"
    if kind == 3:
        return f"mailto:desk{tag}{slot}@help{slot}.io"
    if kind == 4:
        return f"ftp://vault{tag}-{slot}.files.example"
    if kind == 5:
        return f"<https://edge{tag}-{slot}.dev/api>"
    if kind == 6:
        return f"((http://nest{tag}-{slot}.local/path))"
    if kind == 7:
        return f"git://repo{tag}-{slot}.scm/source"
    if kind == 8:
        return f"www.open{tag}-{slot}.com."
    if kind == 9:
        return f"@dup{tag}{slot}@bad{slot}.net"
    return f"note{tag}-{slot}-plain"


def _build_urlize_cases(seed: int) -> list[tuple[str, dict]]:
    digest = hashlib.blake2b(
        f"utils_urlize_s1_cfg:{seed}".encode(), digest_size=64
    ).hexdigest()
    cases: list[tuple[str, dict]] = []
    extra_pool = ("ftp://", "git://", "svn://", "magnet://")

    for case_idx in range(9):
        word_total = 14 + (int(digest[case_idx * 2 : case_idx * 2 + 2], 16) % 7)
        words = [_token_for_slot(digest, case_idx * 31 + word_idx) for word_idx in range(word_total)]
        text = " ".join(words)

        kwargs: dict = {}
        if case_idx % 3 != 1:
            kwargs["trim_url_limit"] = 18 + (case_idx % 4) * 6
        if case_idx % 2 == 0:
            kwargs["rel"] = "noopener"
        if case_idx % 4 == 1:
            kwargs["target"] = "_blank"
        if case_idx % 2 == 1:
            kwargs["extra_schemes"] = extra_pool[: 1 + (case_idx % len(extra_pool))]

        cases.append((text, kwargs))

    return cases


class UrlizeS1CfgTest(unittest.TestCase):
    def test_urlize_middle_invocation_line_path(self) -> None:
        cases = _build_urlize_cases(seed=23)
        outputs = [urlize(text, **kwargs) for text, kwargs in cases]

        self.assertEqual(len(outputs), len(cases))
        self.assertTrue(all(isinstance(item, str) for item in outputs))
        self.assertGreater(sum(len(item) for item in outputs), 800)
        self.assertTrue(any("<a " in item for item in outputs))
