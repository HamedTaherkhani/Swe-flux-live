import io
import pickle
import random
import unittest

from lark import Lark
from lark.exceptions import ConfigurationError


class TestProgrammaticSerializedLoads(unittest.TestCase):
    def test_mixed_direct_load_sources(self):
        rng = random.Random(9041)
        alphabet = "abcdefghjkmnpqrstuvwxyz"
        words = [
            "".join(alphabet[rng.randrange(len(alphabet))] for _ in range(4))
            for _ in range(19)
        ]
        grammar_parts = [
            "start: item (SEP item)*",
            "item: WORD | NUMBER",
            "SEP: /[;|]/",
            "WORD: /[a-z]+/",
            "NUMBER: /[0-9]+/",
            "%import common.WS_INLINE",
            "%ignore WS_INLINE",
        ]
        source_parser = Lark(
            "\n".join(grammar_parts),
            parser="lalr",
        )
        source_parser.__serialize_fields__ = source_parser.__serialize_fields__ + [
            "grammar"
        ]
        saved = io.BytesIO()
        source_parser.save(saved)
        serialized = saved.getvalue()

        for index in range(len(words) + 4):
            payload = pickle.loads(serialized)
            if (index * index + index) % 4:
                payload["data"].pop("grammar", None)
            argument = (
                payload
                if index % 3
                else io.BytesIO(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
            )
            candidate = Lark.__new__(Lark)

            if (index * 5 + 2) % 11 == 1:
                with self.assertRaises(ConfigurationError):
                    candidate._load(argument, parser="earley")
                continue

            loaded = candidate._load(
                argument,
                debug=bool((index * 7) % 2),
                propagate_positions=bool((index + 1) % 3),
            )
            count = 5 + (index * 3) % 9
            pieces = [
                words[(index * 7 + offset * 5) % len(words)]
                if (offset + index) % 3
                else str(rng.randrange(10 ** (1 + (offset % 3))))
                for offset in range(count)
            ]
            separators = [";", "|"]
            text = " ".join(
                piece if not offset else separators[(index + offset) % 2] + " " + piece
                for offset, piece in enumerate(pieces)
            )
            tree = loaded.parse(text)
            self.assertIs(loaded, candidate)
            self.assertEqual(tree.data, "start")
            self.assertEqual(len(tree.children), 2 * len(pieces) - 1)
