import unittest

from lark.exceptions import UnexpectedInput, UnexpectedToken
from lark.lexer import Token


class TestUnexpectedInputDataFlow(unittest.TestCase):
    def test_generated_error_catalog(self):
        state = sum((index * index + 3 * index) % 17 for index in range(23))
        current = UnexpectedToken(
            Token("MARK", "origin"), {"wanted"}, state=state
        )
        current._accepts = {"alpha", "omega"}

        labels = [
            "group_" + "".join(chr(97 + (outer * 7 + step * 11) % 26) for step in range(5))
            for outer in range(6)
        ]
        batches = {
            label: [
                f"case:{outer * 19 + inner * 7 + (outer + inner) % 5}"
                for inner in range(11 + outer % 3)
            ]
            for outer, label in enumerate(labels)
        }

        def parse_generated(text):
            value = int(text.rsplit(":", 1)[1])
            if (value * 5 + 3) % 13 == 0:
                return value
            observed_state = state if (value * 7 + 4) % 6 else state + 1
            error = UnexpectedToken(
                Token("MARK", f"observed_{value * value + 1}"),
                {"wanted"},
                state=observed_state,
            )
            error._accepts = (
                {"alpha", "omega"}
                if (value * 11 + 2) % 5
                else {"alpha", "sigma"}
            )
            raise error

        state_only = current.match_examples(
            parse_generated,
            batches,
            token_type_match_fallback=False,
            use_accepts=True,
        )
        ordered_batches = [
            (label, tuple(reversed(batches[label])))
            for label in reversed(labels)
        ]
        token_fallback = current.match_examples(
            parse_generated,
            ordered_batches,
            token_type_match_fallback=True,
            use_accepts=True,
        )

        self.assertIn(state_only, labels)
        self.assertIn(token_fallback, labels)
        self.assertIsInstance(state_only, str)
        self.assertIsInstance(token_fallback, str)


if __name__ == "__main__":
    unittest.main()
