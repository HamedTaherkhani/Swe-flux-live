import unittest

from sqlglot.anonymize import anonymize
from sqlglot.tokens import TokenType


class TestAnonymizeProgramState(unittest.TestCase):
    def test_generated_mixed_query(self):
        state = 0x5A17
        names = []
        projections = []

        for index in range(48):
            state = (state * 1103515245 + 12345 + index * index) & 0x7FFFFFFF
            width = 3 + state % 7
            generated = "".join(
                chr(ord("a") + ((state >> (offset * 3)) + index + offset) % 26)
                for offset in range(width)
            )

            if names and index % 7 in (0, 3):
                name = names[(state + index) % len(names)]
            else:
                name = f"field_{index % 9}_{generated}"
                names.append(name)

            magnitude = (state ^ (index * 2654435761)) % 900000 + 100000
            if index % 4 == 0:
                number = f"{magnitude / 1000:.3f}"
            elif index % 4 == 1:
                number = f"{magnitude % 900 + 100}e{index % 13 + 2}"
            else:
                number = str(magnitude)

            payload = f"{generated[::-1]}_{(state // 97) % 10000:04d}"
            function = ("COALESCE", "LOWER", "JSON_OBJECT", "ABS")[index % 4]
            if function == "COALESCE":
                expression = f"{function}({name}, '{payload}', {number})"
            elif function == "JSON_OBJECT":
                expression = f"{function}('{generated}', {name})"
            else:
                expression = f"{function}({name})"

            comment = f"/* batch {index % 6}: {payload} */" if index % 5 == 0 else ""
            projections.append(f"{expression} AS out_{index % 11} {comment}")

        table_name = names[(state // 31) % len(names)]
        sql = (
            "SELECT /*+ BROADCAST(private_source) */\n  "
            + ",\n  ".join(projections)
            + f"\nFROM {table_name} -- generated source\n"
            + f"WHERE {names[-1]} <> {state % 700003} AND secret_note = 'unfinished_{state:x}"
        )

        tokens = anonymize(sql)

        self.assertIsInstance(tokens, list)
        self.assertTrue(tokens)
        self.assertEqual(tokens[-1].token_type, TokenType.UNKNOWN)
        self.assertTrue(all(token.text is not None for token in tokens))
