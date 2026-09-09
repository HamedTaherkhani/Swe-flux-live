"""Exercise do_urlize invariant predicates across diverse URLization scenarios."""

from __future__ import annotations

import random
import unittest

from jinja2 import Environment
from jinja2.exceptions import FilterArgumentError
from jinja2.filters import do_urlize
from jinja2.nodes import EvalContext


class TestDoUrlizeInvariantReport(unittest.TestCase):
    """Drive do_urlize directly with programmatic, seeded inputs."""

    SEED = 16180339887

    def setUp(self) -> None:
        self.env = Environment(autoescape=True)
        self.ctx = EvalContext(self.env)

    def _invoke(
        self,
        value: str,
        *,
        env: Environment | None = None,
        trim_url_limit: int | None = None,
        nofollow: bool = False,
        target: str | None = None,
        rel: str | None = None,
        extra_schemes: tuple[str, ...] | None = None,
    ) -> str:
        eval_ctx = EvalContext(env or self.env)
        return do_urlize(
            eval_ctx,
            value,
            trim_url_limit=trim_url_limit,
            nofollow=nofollow,
            target=target,
            rel=rel,
            extra_schemes=extra_schemes,
        )

    def test_programmatic_mixed_urls(self) -> None:
        rng = random.Random(self.SEED + 1)
        hosts = [f"host{idx}.example" for idx in range(50)]
        rng.shuffle(hosts)
        parts = []
        for host in hosts:
            pick = rng.randint(0, 3)
            if pick == 0:
                scheme = "https://"
            elif pick == 1:
                scheme = "http://"
            elif pick == 2:
                scheme = "www."
            else:
                scheme = "ftp://"
            parts.append(f"see {scheme}{host}/docs next")
        text = " ".join(parts)
        result = self._invoke(text)
        self.assertIn("<a href=", result)
        self.assertGreater(result.count("<a "), 25)

    def test_http_https_variants(self) -> None:
        base = sum(ord(ch) for ch in "http_https_variants")
        urls = [
            f"http://site{idx}.org/page{base % 7}" for idx in range(14)
        ] + [
            f"https://secure{idx}.org/api{base % 5}" for idx in range(14)
        ] + [
            f"www.portal{idx}.net/entry{idx % 4}" for idx in range(8)
        ]
        text = " | ".join(urls)
        result = self._invoke(text)
        self.assertEqual(result.count('href="http://'), 14)
        self.assertEqual(result.count('href="https://'), 22)

    def test_email_and_mailto(self) -> None:
        rng = random.Random(self.SEED + 3)
        mailboxes = [
            f"user{idx}@mail{rng.randint(1, 12)}.example"
            for idx in range(32)
        ]
        chunks = []
        for mailbox in mailboxes:
            if rng.randint(0, 2) == 0:
                chunks.append(f"mailto:{mailbox}")
            else:
                chunks.append(mailbox)
        text = ", ".join(chunks)
        result = self._invoke(text)
        self.assertGreaterEqual(result.count("mailto:"), 18)

    def test_nofollow_enabled(self) -> None:
        rng = random.Random(self.SEED + 4)
        links = [
            f"https://ref{idx}.example/article"
            for idx in range(rng.randint(18, 28))
        ]
        text = " ".join(links)
        result = self._invoke(text, nofollow=True)
        self.assertGreater(result.count('rel="'), 0)
        self.assertIn("nofollow", result)

    def test_custom_rel_and_target(self) -> None:
        rng = random.Random(self.SEED + 5)
        pages = [f"www.page{idx}.example" for idx in range(22)]
        text = " ".join(pages)
        result = self._invoke(
            text,
            rel="noopener noreferrer license external",
            target="_blank",
        )
        self.assertIn('target="_blank"', result)
        self.assertIn("license", result)

    def test_policy_rel_cleared(self) -> None:
        env = Environment(autoescape=False)
        env.policies["urlize.rel"] = None
        pages = [f"www.plain{idx}.example" for idx in range(20)]
        text = " ".join(pages)
        result = self._invoke(text, env=env, rel=None, nofollow=False)
        self.assertNotIn('rel="noopener"', result)
        self.assertEqual(result.count("<a href="), 20)

    def test_extra_schemes_batch(self) -> None:
        rng = random.Random(self.SEED + 7)
        schemes = (
            "tel:", "ftp:", "git:", "svn:", "ssh:", "magnet:",
            "sip:", "sftp:", "vnc:", "ldap:", "nfs:", "rsync:",
        )
        picks = rng.sample(schemes, k=8)
        tokens = [f"{scheme}resource{idx}" for idx, scheme in enumerate(picks)]
        text = " ".join(tokens)
        result = self._invoke(text, extra_schemes=picks)
        self.assertEqual(result.count("<a href="), len(picks))

    def test_policy_extra_schemes(self) -> None:
        env = Environment(autoescape=False)
        env.policies["urlize.extra_schemes"] = (
            "irc:", "xmpp:", "news:", "nntp:", "gopher:", "wais:",
        )
        rng = random.Random(self.SEED + 8)
        items = [
            "irc://chan0.net",
            "xmpp:user1@host",
            "news:group2.dev",
            "nntp://list3.example",
            "gopher://hole4.org",
            "wais://index5.info",
        ]
        rng.shuffle(items)
        text = " / ".join(items)
        result = self._invoke(text, env=env)
        self.assertEqual(result.count("<a href="), 6)

    def test_many_scheme_validation(self) -> None:
        rng = random.Random(self.SEED + 9)
        schemes = tuple(f"p{idx}{'+-.'[idx % 3]}:" for idx in range(50))
        tokens = [f"{scheme}item{idx}" for idx, scheme in enumerate(schemes)]
        rng.shuffle(tokens)
        text = " ".join(tokens)
        result = self._invoke(text, extra_schemes=schemes)
        self.assertEqual(result.count("<a href="), len(schemes))

    def test_trim_url_limit(self) -> None:
        rng = random.Random(self.SEED + 10)
        long_urls = [
            f"https://long{idx}.example/" + "x" * (rng.randint(8, 35))
            for idx in range(24)
        ]
        text = " ".join(long_urls)
        limit = 14
        result = self._invoke(text, trim_url_limit=limit)
        self.assertGreater(result.count("..."), 12)

    def test_empty_value(self) -> None:
        result = self._invoke("")
        self.assertEqual(result, "")

    def test_invalid_extra_scheme(self) -> None:
        with self.assertRaises(FilterArgumentError):
            self._invoke(
                "visit badscheme:broken and x:alsobad",
                extra_schemes=("badscheme", "x"),
            )

    def test_repeated_invocations(self) -> None:
        rng = random.Random(self.SEED + 13)
        total_links = 0
        for repeat in range(55):
            host = f"loop{repeat}.example"
            prefix = "https://" if repeat % 3 == 0 else "www."
            text = f"item {prefix}{host}/r{repeat}"
            result = self._invoke(text)
            total_links += result.count("<a ")
        self.assertGreater(total_links, 50)

    def test_paren_wrapped_urls(self) -> None:
        rng = random.Random(self.SEED + 14)
        wrapped = []
        for idx in range(28):
            host = f"wrap{idx}.example"
            if idx % 3 == 0:
                wrapped.append(f"(see www.{host})")
            elif idx % 3 == 1:
                wrapped.append(f"<https://{host}/path>")
            else:
                wrapped.append(f"({host}/docs).")
        text = " ".join(wrapped)
        result = self._invoke(text)
        self.assertGreaterEqual(result.count("<a "), 18)

    def test_mixed_scheme_policy_combo(self) -> None:
        env = Environment(autoescape=False)
        env.policies["urlize.extra_schemes"] = ("data:", "file:", "blob:")
        env.policies["urlize.target"] = "_parent"
        schemes = ("data:", "file:", "blob:", "custom:", "view-source:")
        rng = random.Random(self.SEED + 15)
        tokens = [
            f"{scheme}payload{idx}"
            for idx, scheme in enumerate(schemes)
        ]
        rng.shuffle(tokens)
        text = " ".join(tokens)
        result = self._invoke(
            text,
            env=env,
            extra_schemes=("custom:", "view-source:"),
            target=None,
        )
        self.assertGreaterEqual(result.count('target="_parent"'), 1)


if __name__ == "__main__":
    unittest.main()
