import random
import unittest

from sqlglot import exp
from sqlglot.dialects.trino import Trino
from sqlglot.parsers.trino import TrinoParser


class TestTrinoRoutineCallFlow(unittest.TestCase):
    def test_generated_routine_tree(self):
        rng = random.Random(7319)
        values = []
        state = rng.randrange(17, 97)
        for index in range(24):
            state = (state * 37 + index * 11 + rng.randrange(5, 41)) % 211
            values.append(state + 3)

        kinds = [kind for _ in range(3) for kind in range(6)]
        rng.shuffle(kinds)
        statements = ["DECLARE x BIGINT DEFAULT 0"]

        for index, kind in enumerate(kinds):
            first, second = values[index], values[index + 3]
            label = f"phase_{index}_{values[index + 5]}"

            if kind == 0:
                statement = (
                    f"BEGIN SET x = x + {first}; "
                    f"IF x > {second} THEN SET x = x - 1; "
                    "ELSE SET x = x + 2; END IF; END"
                )
            elif kind == 1:
                statement = (
                    f"IF x < {first} THEN SET x = x + {second}; "
                    f"ELSEIF x = {second} THEN SET x = x - {first}; "
                    "ELSE SET x = x + 1; END IF"
                )
            elif kind == 2:
                statement = (
                    f"CASE x WHEN {first} THEN SET x = x + 1; "
                    f"WHEN {second} THEN SET x = x - 1; "
                    "ELSE SET x = x + 3; END CASE"
                )
            elif kind == 3:
                statement = (
                    f"{label}: WHILE x < {first} DO SET x = x + {second}; "
                    f"IF x > {second} THEN ITERATE {label}; ELSE LEAVE {label}; END IF; "
                    "END WHILE"
                )
            elif kind == 4:
                statement = (
                    f"{label}: LOOP CASE x WHEN {first} THEN SET x = x + {second}; "
                    "ELSE SET x = x + 4; END CASE; "
                    f"LEAVE {label}; END LOOP"
                )
            else:
                statement = (
                    f"{label}: REPEAT SET x = x + {first}; "
                    f"IF x > {second} THEN SET x = x - 2; ELSE SET x = x + 5; END IF; "
                    f"UNTIL x > {first + second} END REPEAT"
                )

            statements.append(statement)

        statements.append("RETURN x")
        sql = "BEGIN " + "; ".join(statements) + "; END"
        dialect = Trino()
        routine_parser = TrinoParser(dialect=dialect)
        parsed = routine_parser._parse(
            lambda _: routine_parser._parse_routine_statement(),
            dialect.tokenize(sql),
            sql,
        )

        self.assertEqual(len(parsed), 1)
        self.assertIsInstance(parsed[0], exp.Block)
        self.assertTrue(parsed[0].args["begin"])
        self.assertGreater(sum(1 for _ in parsed[0].walk()), len(kinds))
        self.assertGreater(len(parsed[0].sql(dialect=dialect)), len(sql) // 2)
