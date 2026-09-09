import unittest

from lark import Lark
from lark.lexer import Token


class TestLalrParserRecovery(unittest.TestCase):
    def test_generated_recovery_stream(self):
        grammar = r"""
            start: "[" number ("," number)* "]"
            ?number: SIGNED_NUMBER
            %import common.SIGNED_NUMBER
            %ignore " "
        """
        configured = Lark(grammar, parser="lalr")

        values = [((index * 37) % 211) - 83 for index in range(48)]
        fragments = ["["]
        for index, value in enumerate(values):
            if index:
                if index % 7 == 0:
                    fragments.append("@")
                elif index % 5 == 0:
                    fragments.append(",,,")
                elif index % 3 == 0:
                    fragments.append(" ")
                else:
                    fragments.append(",")
            fragments.append(str(value))
            if index % 11 == 0:
                fragments.append("#")
        fragments.append("]")
        text = "".join(fragments)

        def recover(error):
            token = getattr(error, "token", None)
            if token is None:
                return True
            if token.type == "COMMA":
                return True
            if token.type == "SIGNED_NUMBER":
                error.interactive_parser.feed_token(Token("COMMA", ","))
                error.interactive_parser.feed_token(token)
                return True
            return False

        frontend = configured.parser
        lexer_thread = frontend._make_lexer_thread(text)
        target = frontend.parser
        tree = target.parse(lexer_thread, "start", on_error=recover)

        self.assertEqual([int(item) for item in tree.children], values)
