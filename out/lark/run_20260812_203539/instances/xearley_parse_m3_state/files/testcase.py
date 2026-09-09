import random
import unittest

from lark import Lark
from lark.grammar import NonTerminal
from lark.parsers.earley_common import Item
from lark.parsers.xearley import Parser


class TestXearleyParseProgramState(unittest.TestCase):
    def _drive(self, grammar, source, *, complete=False):
        configured = Lark(
            grammar,
            parser="earley",
            lexer="dynamic_complete" if complete else "dynamic",
            ambiguity="explicit",
        )
        backend = configured.parser.parser
        self.assertIsInstance(backend, Parser)

        start_symbol = NonTerminal("start")
        columns = [backend.Set()]
        to_scan = backend.Set()
        for rule in backend.predictions[start_symbol]:
            item = Item(rule, 0, 0)
            if item.expect in backend.TERMINALS:
                to_scan.add(item)
            else:
                columns[0].add(item)

        final_scan = backend._parse(source, columns, to_scan, start_symbol)
        completed = [
            item
            for item in columns[-1]
            if item.is_complete and item.s == start_symbol and item.start == 0
        ]
        self.assertEqual(len(columns), len(source) + 1)
        self.assertTrue(completed)
        self.assertIsInstance(final_scan, backend.Set)

    def test_01_generated_word_train(self):
        rng = random.Random(113)
        words = [
            "".join(chr(97 + rng.randrange(18)) for _ in range(2 + index % 5))
            for index in range(19)
        ]
        source = " ".join(words)
        self._drive(
            """
            start: WORD+
            WORD: /[a-r]+/
            %import common.WS
            %ignore WS
            """,
            source,
        )

    def test_02_generated_key_value_records(self):
        rng = random.Random(227)
        records = []
        for index in range(17):
            key = "".join(chr(97 + rng.randrange(12)) for _ in range(3 + index % 3))
            value = str((index * index + rng.randrange(40)) % 97)
            records.append(key + ":" + value)
        source = ";".join(records)
        self._drive(
            """
            start: record (";" record)*
            record: NAME ":" INT
            NAME: /[a-l]+/
            %import common.INT
            """,
            source,
        )

    def test_03_nested_balanced_groups(self):
        atoms = [chr(97 + (index * 11) % 23) for index in range(21)]
        source = atoms[0]
        for index, atom in enumerate(atoms[1:], 1):
            source = "(" + source + ("+" if index % 2 else "-") + atom + ")"
        self._drive(
            """
            start: expr
            ?expr: ATOM | "(" expr OP expr ")"
            OP: "+" | "-"
            ATOM: /[a-w]/
            """,
            source,
        )

    def test_04_optional_suffix_sequence(self):
        rng = random.Random(331)
        chunks = []
        for index in range(24):
            stem = chr(97 + rng.randrange(20)) * (1 + index % 4)
            suffix = "!" if index % 4 == 1 else "?" if index % 7 == 3 else ""
            chunks.append(stem + suffix)
        source = " ".join(chunks)
        self._drive(
            """
            start: unit+
            unit: STEM SUFFIX?
            STEM: /[a-t]+/
            SUFFIX: "!" | "?"
            %import common.WS
            %ignore WS
            """,
            source,
        )

    def test_05_multiline_indented_rows(self):
        rows = []
        for index in range(16):
            indent = " " * (1 + (index * 3) % 5)
            word = chr(97 + (index * 5) % 17) * (2 + index % 4)
            rows.append(indent + word)
        source = "\n".join(rows)
        self._drive(
            """
            start: (_WS WORD _NL)* _WS WORD
            WORD: /[a-q]+/
            _WS: / +/
            _NL: /\\n/
            """,
            source,
        )

    def test_06_generated_arithmetic_chain(self):
        rng = random.Random(443)
        terms = [str(1 + ((index * 13 + rng.randrange(20)) % 89)) for index in range(22)]
        operators = ["+", "*", "-", "+", "*"]
        source = terms[0]
        for index, term in enumerate(terms[1:]):
            source += operators[(index * 3 + 1) % len(operators)] + term
        self._drive(
            """
            start: NUMBER (OP NUMBER)+
            OP: "+" | "-" | "*"
            %import common.NUMBER
            """,
            source,
        )

    def test_07_variable_width_csv(self):
        rng = random.Random(557)
        fields = []
        for index in range(20):
            fields.append(
                "".join(chr(65 + rng.randrange(18)) for _ in range(1 + (index * 2) % 6))
            )
        source = ",".join(fields)
        self._drive(
            """
            start: FIELD ("," FIELD)*
            FIELD: /[A-R]+/
            """,
            source,
        )

    def test_08_complete_lex_segmentations(self):
        rng = random.Random(661)
        source = "".join(chr(97 + rng.randrange(6)) for _ in range(18))
        self._drive(
            """
            start: piece+
            piece: SHORT | LONG
            SHORT: /[a-f]{1,2}/
            LONG: /[a-f]{3,5}/
            """,
            source,
            complete=True,
        )

    def test_09_delimited_numeric_batches(self):
        batches = []
        for outer in range(8):
            values = [str((outer * 17 + inner * inner * 3) % 101) for inner in range(3 + outer % 4)]
            batches.append("[" + ",".join(values) + "]")
        source = "|".join(batches)
        self._drive(
            """
            start: batch ("|" batch)*
            batch: "[" INT ("," INT)* "]"
            %import common.INT
            """,
            source,
        )

    def test_10_keyword_identifier_ambiguity(self):
        rng = random.Random(773)
        chunks = []
        for index in range(21):
            if index % 5 == 2:
                chunks.append("if")
            elif index % 6 == 1:
                chunks.append("in")
            else:
                chunks.append(
                    "".join(chr(97 + rng.randrange(14)) for _ in range(2 + index % 5))
                )
        source = " ".join(chunks)
        self._drive(
            """
            start: token+
            token: KEYWORD | IDENT
            KEYWORD: "if" | "in"
            IDENT: /[a-n]+/
            %import common.WS
            %ignore WS
            """,
            source,
        )

    def test_11_generated_assignment_lines(self):
        rng = random.Random(887)
        lines = []
        for index in range(15):
            name = chr(97 + index % 11) + "".join(
                chr(97 + rng.randrange(16)) for _ in range(2 + index % 3)
            )
            number = (index * 29 + rng.randrange(70)) % 211
            lines.append(name + "=" + str(number))
        source = "\n".join(lines)
        self._drive(
            """
            start: assignment (_NL assignment)*
            assignment: NAME "=" INT
            NAME: /[a-p]+/
            %import common.INT
            _NL: /\\n/
            """,
            source,
        )

    def test_12_mixed_bracket_blocks(self):
        rng = random.Random(991)
        blocks = []
        openings = [("(", ")"), ("[", "]"), ("{", "}")]
        for index in range(18):
            left, right = openings[(index * 2 + 1) % len(openings)]
            body = "".join(chr(97 + rng.randrange(10)) for _ in range(2 + index % 5))
            blocks.append(left + body + right)
        source = "".join(blocks)
        self._drive(
            """
            start: block+
            block: "(" BODY ")" | "[" BODY "]" | "{" BODY "}"
            BODY: /[a-j]+/
            """,
            source,
        )
