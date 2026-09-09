import random
import unittest

from lark import Lark


class TestParsingFrontendScanExceptions(unittest.TestCase):
    def test_generated_mixed_candidates(self):
        rng = random.Random(731946)
        class_names = [
            "".join(("Candidate", "Rejection", chr(ord("A") + index)))
            for index in range(4)
        ]
        rejection_types = [
            type(name, (ValueError,), {"__module__": __name__})
            for name in class_names
        ]
        callback_calls = 0

        def validate_item(token):
            nonlocal callback_calls
            callback_calls += 1
            if callback_calls % 6 == 0:
                rejection = rejection_types[(callback_calls // 6) % len(rejection_types)]
                raise rejection(token.value)
            return token

        parser = Lark(
            r"""
            start: OPEN ITEM ITEM CLOSE
            OPEN: "["
            CLOSE: "]"
            ITEM: /[a-z]{3,8}/
            %ignore /\s+/
            """,
            parser="lalr",
            lexer="basic",
            lexer_callbacks={"ITEM": validate_item},
        )

        alphabet = "abcdefghijkmnopqrstuvwxyz"

        def word(index):
            width = 3 + (index % 6)
            return "".join(rng.choice(alphabet) for _ in range(width))

        candidates = []
        for index in range(48):
            item_count = (index * 7 + index // 3) % 4
            items = " ".join(word(index * 5 + offset) for offset in range(item_count))
            candidates.append(f"[ {items} ]")

        text = " :: ".join(candidates)
        matches = list(parser.scan(text))

        self.assertGreater(callback_calls, len(candidates))
        self.assertTrue(matches)
        self.assertTrue(all(match.range[0] < match.range[1] for match in matches))

