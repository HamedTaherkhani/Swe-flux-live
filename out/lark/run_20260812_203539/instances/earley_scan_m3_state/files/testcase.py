import random
import unittest

from lark import Lark


GRAMMAR = r"""
start: row+

row: NAME assignment expression terminator
   | NAME EQ expression terminator

assignment: EQ | COLON EQ
?expression: atom
           | atom operator expression
           | atom atom
?atom: NUMBER
     | NAME
     | sign NUMBER
     | LPAR expression RPAR
sign: PLUS | MINUS
operator: PLUS | MINUS | STAR | SLASH
terminator: SEMI | BANG SEMI

EQ: "="
COLON: ":"
PLUS: "+"
MINUS: "-"
STAR: "*"
SLASH: "/"
LPAR: "("
RPAR: ")"
SEMI: ";"
BANG: "!"
NAME: /[a-z][a-z0-9_]*/
NUMBER: /[0-9]+/
COMMENT: /#[^\n]*/

%import common.WS
%ignore WS
%ignore COMMENT
"""


class EarleyScanProgramStateTests(unittest.TestCase):
    def _run_case(self, seed, rows, width_shift, signed_stride, nested_stride, bang_stride):
        rng = random.Random(seed)
        operators = ("+", "-", "*", "/")
        statements = []

        for row_index in range(rows):
            atom_count = 2 + ((row_index + width_shift) % 4)
            atoms = []
            for atom_index in range(atom_count):
                selector = (rng.randrange(97) + row_index + atom_index + width_shift) % 3
                if selector == 0:
                    atom = str(rng.randrange(3, 9000))
                    if (row_index + atom_index) % signed_stride == 0:
                        atom = ("+", "-")[(row_index + atom_index + width_shift) % 2] + atom
                else:
                    atom = f"v{row_index:x}_{atom_index:x}_{rng.randrange(5, 4000):x}"

                if atom_index == atom_count - 1 and row_index % nested_stride == 0:
                    nested_number = rng.randrange(7, 7000)
                    nested_name = f"n{rng.randrange(11, 3000):x}"
                    nested_op = operators[(row_index + width_shift) % len(operators)]
                    atom = f"({nested_number} {nested_op} {nested_name})"
                atoms.append(atom)

            expression_parts = [atoms[0]]
            for atom_index, atom in enumerate(atoms[1:], 1):
                op = operators[(rng.randrange(len(operators)) + row_index + atom_index) % len(operators)]
                expression_parts.extend((op, atom))

            assignment = ": =" if (row_index + width_shift) % 3 == 0 else "="
            terminator = "! ;" if row_index % bang_stride == width_shift % bang_stride else ";"
            comment = ""
            if (row_index + seed) % 4 == 0:
                comment = f" # c{rng.randrange(17, 10000):x}"
            statements.append(
                f"item_{width_shift:x}_{row_index:x} {assignment} "
                f"{' '.join(expression_parts)} {terminator}{comment}"
            )

        tree = Lark(GRAMMAR, parser="earley", lexer="basic", ambiguity="resolve").parse(
            "\n".join(statements)
        )
        self.assertEqual(tree.data, "start")
        self.assertEqual(len(tree.children), rows)
        self.assertTrue(all(child.data == "row" for child in tree.children))

    def test_dense_short_rows(self):
        self._run_case(104729, 16, 1, 2, 3, 2)

    def test_sparse_nested_rows(self):
        self._run_case(130363, 15, 4, 5, 7, 4)

    def test_signed_number_mix(self):
        self._run_case(155921, 17, 2, 2, 5, 3)

    def test_wide_expression_cycle(self):
        self._run_case(196613, 18, 7, 4, 6, 5)

    def test_frequent_nested_groups(self):
        self._run_case(225287, 15, 3, 3, 2, 4)

    def test_rare_signed_values(self):
        self._run_case(262147, 19, 5, 8, 4, 6)

    def test_alternating_terminators(self):
        self._run_case(294001, 16, 6, 5, 3, 2)

    def test_long_operator_chain(self):
        self._run_case(327673, 20, 10, 4, 8, 7)

    def test_compact_nested_chain(self):
        self._run_case(360007, 15, 0, 3, 2, 3)

    def test_shifted_branch_pattern(self):
        self._run_case(393241, 17, 8, 6, 5, 4)

    def test_prime_seed_rows(self):
        self._run_case(425977, 18, 9, 7, 3, 5)

    def test_extended_mixed_rows(self):
        self._run_case(458689, 21, 11, 5, 4, 3)
