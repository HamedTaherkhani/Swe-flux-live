import json
import random
import unittest

from lark import Lark


GRAMMAR = r"""
start: statement+
statement: NAME ASSIGN expr SEP?
?expr: atom (OP atom)*
?atom: NUMBER | NAME | STRING | LPAR expr RPAR

ASSIGN: "=" | ":="
OP: "+" | "-" | "*" | "/"
SEP: ";" | "|"
LPAR: "("
RPAR: ")"
NAME: /[a-z][a-z0-9_]*/
NUMBER: /[0-9]+(?:\.[0-9]+)?/
STRING: /"[^"\\]*(?:\\.[^"\\]*)*"/
COMMENT: /#[^\n]*/

%import common.WS
%ignore WS
%ignore COMMENT
"""


class LexerProgramStateTests(unittest.TestCase):
    def _run_case(self, seed, rows, mode, comment_stride, shape):
        rng = random.Random(seed)
        callback_counts = {"COMMENT": 0, "NAME": 0, "NUMBER": 0}

        def transform(token):
            callback_counts[token.type] += 1
            raw = token.value
            score = sum((index + mode + 1) * ord(ch) for index, ch in enumerate(raw))
            token.value = f"{token.type.lower()}_{score:x}_{callback_counts[token.type] * (mode + 3)}"
            return token

        parser = Lark(
            GRAMMAR,
            parser="lalr",
            lexer="contextual",
            lexer_callbacks={
                "COMMENT": transform,
                "NAME": transform,
                "NUMBER": transform,
            },
        )

        statements = []
        operators = ("+", "-", "*", "/")
        for row in range(rows):
            lhs = f"v{mode}_{row}_{rng.randrange(17, 997)}"
            atom_count = 2 + ((row + shape) % 4)
            atoms = []
            for column in range(atom_count):
                selector = (rng.randrange(100) + row + column + shape) % 4
                if selector == 0:
                    atom = str(rng.randrange(11, 9999))
                elif selector == 1:
                    atom = f"ref_{mode}_{rng.randrange(13, 701)}"
                elif selector == 2:
                    atom = json.dumps(
                        "".join(chr(97 + rng.randrange(26)) for _ in range(3 + (row + column) % 6))
                    )
                else:
                    inner = f"{rng.randrange(19, 809)} {operators[(row + column) % 4]} ref_{rng.randrange(23, 887)}"
                    atom = f"({inner})"
                atoms.append(atom)

            pieces = [atoms[0]]
            for column, atom in enumerate(atoms[1:], 1):
                pieces.extend((operators[(rng.randrange(4) + column + shape) % 4], atom))
            assignment = ":=" if (row + mode + shape) % 3 == 0 else "="
            separator = (";", "|")[(row + shape) % 2]
            statement = f"{lhs} {assignment} {' '.join(pieces)} {separator}"
            if row % comment_stride == (shape % comment_stride):
                payload = "".join(chr(97 + rng.randrange(26)) for _ in range(5 + row % 9))
                statement += f" #c{mode}_{row:x}_{payload}_{rng.randrange(29, 1009):x}"
            statements.append(statement)

        tree = parser.parse("\n".join(statements))
        self.assertEqual(tree.data, "start")
        self.assertEqual(len(tree.children), rows)
        self.assertGreater(callback_counts["NAME"], rows)
        self.assertGreater(callback_counts["NUMBER"] + callback_counts["COMMENT"], 0)

    def test_dense_comments_and_nested_atoms(self):
        self._run_case(104729, 18, 2, 2, 1)

    def test_sparse_comments_with_long_rows(self):
        self._run_case(130363, 16, 5, 5, 3)

    def test_alternating_assignment_forms(self):
        self._run_case(155921, 19, 1, 3, 2)

    def test_many_parenthesized_atoms(self):
        self._run_case(196613, 17, 7, 4, 6)

    def test_string_heavy_mixture(self):
        self._run_case(225287, 20, 3, 6, 4)

    def test_numeric_heavy_mixture(self):
        self._run_case(262147, 15, 9, 2, 7)

    def test_short_rows_frequent_comments(self):
        self._run_case(294001, 21, 4, 2, 0)

    def test_long_rows_rare_comments(self):
        self._run_case(327673, 18, 8, 7, 5)

    def test_separator_phase_shift(self):
        self._run_case(360007, 22, 6, 3, 8)

    def test_operator_phase_shift(self):
        self._run_case(393241, 16, 10, 4, 9)

    def test_compact_seeded_program(self):
        self._run_case(425977, 15, 11, 5, 10)

    def test_extended_seeded_program(self):
        self._run_case(458689, 23, 12, 3, 11)
