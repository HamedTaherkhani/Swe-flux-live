import random
import unittest

from lark.lexer import Token
from lark.parsers.lalr_parser import _Parser


class _GeneratedLexer:
    def __init__(self, values):
        self._values = values

    def lex(self, state):
        for index, value in enumerate(self._values):
            yield Token("ITEM", f"{index:x}:{value:x}")


class _GeneratedState:
    def __init__(self, values, fail_after, mode):
        self.lexer = _GeneratedLexer(values)
        self.fail_after = fail_after
        self.mode = mode
        self.feed_count = 0
        self.checksum = 0

    def feed_token(self, token, is_end=False):
        self.feed_count += 1
        self.checksum = ((self.checksum << 3) ^ ord(token[0])) & 0xFFFF
        if self.feed_count != self.fail_after:
            return self.checksum

        selector = self.mode
        if selector == 0:
            return {}[token]
        if selector == 1:
            return self.feed_count // (self.fail_after - self.feed_count)
        if selector == 2:
            return getattr(token, "".join(chr(code) for code in (117, 110, 115, 101, 101, 110)))
        if selector == 3:
            return [token][self.feed_count]
        return token + self.feed_count


class ParseFromStateExceptionBehaviorTests(unittest.TestCase):
    def test_generated_failures_across_parser_runs(self):
        rng = random.Random(0x5A17)
        mode_order = list(range(5))
        rng.shuffle(mode_order)
        specs = [
            (
                16 + rng.randrange(18),
                mode_order[index % len(mode_order)],
                [rng.randrange(1, 1 << 20) ^ (index * 313 + offset) for offset in range(48)],
            )
            for index in range(25)
        ]

        parser = _Parser(parse_table=None, callbacks={}, debug=False)
        observed = []
        for fail_after, mode, values in specs:
            state = _GeneratedState(values, fail_after, mode)
            try:
                parser.parse_from_state(state)
            except BaseException:
                observed.append((state.feed_count, state.checksum))

        self.assertEqual(len(observed), len(specs))
        self.assertTrue(all(count == spec[0] for (count, _), spec in zip(observed, specs)))
        self.assertGreater(sum(checksum != 0 for _, checksum in observed), 20)
