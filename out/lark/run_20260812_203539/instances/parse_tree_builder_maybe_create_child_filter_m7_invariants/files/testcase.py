import random
import string
import unittest

from lark import Lark, Tree


class TestGeneratedParseTreeBuilders(unittest.TestCase):
    def _exercise(self, label, width, parser_name, placeholders, keep_tokens, explicit):
        rng = random.Random(sum((index + 3) * ord(char) for index, char in enumerate(label)))
        alphabet = string.ascii_lowercase
        used = set()
        words = []
        while len(words) < width:
            size = rng.randrange(4, 9)
            word = "".join(rng.choice(alphabet) for _ in range(size))
            if word not in used:
                used.add(word)
                words.append(word)

        parts = []
        definitions = []
        input_words = []
        for index, word in enumerate(words):
            shape = (index + rng.randrange(7) + len(label)) % 4
            optional = (index * 3 + rng.randrange(5)) % 6 == 0
            present = not optional or (index + sum(map(ord, label))) % 3 != 0
            if shape == 0:
                symbol = '"%s"' % word
            elif shape == 1:
                symbol = "node_%s" % index
                definitions.append('%s: "%s"' % (symbol, word))
            elif shape == 2:
                symbol = "_inline_%s" % index
                definitions.append('%s: "%s"' % (symbol, word))
            else:
                symbol = "TERM_%s" % index
                definitions.append('%s: "%s"' % (symbol, word))
            if optional:
                wrapper = "maybe_%s" % index
                definitions.append("%s: [%s]" % (wrapper, symbol))
                parts.append(wrapper)
            else:
                parts.append(symbol)
            if present:
                input_words.append(word)

        grammar = "\n".join(
            ["start: " + " ".join(parts)]
            + definitions
            + ["WS: /[ ]+/", "%ignore WS"]
        )
        options = {
            "parser": parser_name,
            "maybe_placeholders": placeholders,
            "keep_all_tokens": keep_tokens,
            "cache": False,
        }
        if explicit:
            options["ambiguity"] = "explicit"
        parser = Lark(grammar, **options)
        result = parser.parse(" ".join(input_words))
        self.assertIsInstance(result, Tree)
        self.assertEqual(result.data, "start")
        self.assertGreaterEqual(len(result.children), 1)

    def test_01_lalr_placeholders(self):
        self._exercise("amber-field", 23, "lalr", True, False, False)

    def test_02_lalr_compact(self):
        self._exercise("birch-cove", 19, "lalr", False, False, False)

    def test_03_lalr_keep_tokens(self):
        self._exercise("cinder-glen", 27, "lalr", True, True, False)

    def test_04_earley_resolve(self):
        self._exercise("dahlia-port", 21, "earley", True, False, False)

    def test_05_earley_explicit(self):
        self._exercise("elm-ridge", 25, "earley", True, False, True)

    def test_06_earley_keep_tokens(self):
        self._exercise("fir-harbor", 18, "earley", False, True, False)

    def test_07_lalr_long_sparse(self):
        self._exercise("garnet-isle", 31, "lalr", True, False, False)

    def test_08_earley_compact(self):
        self._exercise("hazel-marsh", 22, "earley", False, False, False)

    def test_09_lalr_dense(self):
        self._exercise("indigo-peak", 29, "lalr", False, True, False)

    def test_10_earley_long_explicit(self):
        self._exercise("juniper-bay", 33, "earley", True, False, True)

    def test_11_lalr_short_edge(self):
        self._exercise("kelp-valley", 17, "lalr", True, True, False)

    def test_12_earley_mixed_edge(self):
        self._exercise("lilac-delta", 24, "earley", True, False, False)


if __name__ == "__main__":
    unittest.main()
