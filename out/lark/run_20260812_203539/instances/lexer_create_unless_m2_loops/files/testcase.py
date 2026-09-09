import random
import string
import unittest

from lark import Lark


class TestCreateUnlessLoopDynamics(unittest.TestCase):
    def _exercise_generated_grammar(self, tag):
        rng = random.Random(sum(map(ord, tag)))
        keyword_count = len(tag) + sum(rng.randrange(1, 7) for _ in tag)
        regex_count = 2 + sum(map(ord, tag)) % 6

        keywords = []
        while len(keywords) < keyword_count:
            width = rng.randrange(3, 9)
            word = "".join(rng.choice(string.ascii_lowercase) for _ in range(width))
            if word not in keywords:
                keywords.append(word)

        terminal_names = []
        definitions = []
        for index, word in enumerate(keywords):
            name = "KW_%s" % index
            priority = 1 + (index + len(tag)) % 3
            terminal_names.append(name)
            definitions.append('%s.%s: "%s"' % (name, priority, word))

        for index in range(regex_count):
            name = "RX_%s" % index
            priority = 1 + (index + sum(map(ord, tag))) % 3
            minimum = 1 + index % 6
            terminal_names.append(name)
            definitions.append("%s.%s: /[a-z]{%s,}/" % (name, priority, minimum))

        grammar = "\n".join(
            ["start: (%s)+" % " | ".join(terminal_names)]
            + definitions
            + ["WS: /[ ]+/", "%ignore WS"]
        )
        parser = Lark(grammar, parser="lalr", lexer="basic", cache=False)

        sample = keywords[:: max(1, len(keywords) // 7)]
        tokens = list(parser.lex(" ".join(sample)))
        self.assertTrue(tokens)
        self.assertLessEqual(len(tokens), len(sample))
        self.assertTrue(all(token.value in sample for token in tokens))

    def test_01_amber(self):
        self._exercise_generated_grammar("amber")

    def test_02_birchwood(self):
        self._exercise_generated_grammar("birchwood")

    def test_03_cobalt_ridge(self):
        self._exercise_generated_grammar("cobaltridge")

    def test_04_delta(self):
        self._exercise_generated_grammar("delta")

    def test_05_evergreen_arc(self):
        self._exercise_generated_grammar("evergreenarc")

    def test_06_fjord(self):
        self._exercise_generated_grammar("fjord")

    def test_07_glacier_field(self):
        self._exercise_generated_grammar("glacierfield")

    def test_08_harbor_stone(self):
        self._exercise_generated_grammar("harborstone")

    def test_09_indigo(self):
        self._exercise_generated_grammar("indigo")

    def test_10_juniper_vale(self):
        self._exercise_generated_grammar("junipervale")

    def test_11_kingfisher_bay(self):
        self._exercise_generated_grammar("kingfisherbay")

    def test_12_lantern(self):
        self._exercise_generated_grammar("lantern")


if __name__ == "__main__":
    unittest.main()
