import unittest
from types import SimpleNamespace

from lark.lexer import Token
from lark.parsers.lalr_analysis import Shift
from lark.parsers.lalr_parser_state import ParserState


class _Origin:
    def __init__(self, name):
        self.name = name


class _Rule:
    def __init__(self, name, size):
        self.origin = _Origin(name)
        self.expansion = [None] * size


class TestParserStateFeedToken(unittest.TestCase):
    def test_reduction_chain(self):
        seed = 24681357
        initial_values = []
        for index in range(49):
            seed = (seed * 1103515245 + 12345 + index * index) & 0x7FFFFFFF
            initial_values.append(((seed >> 7) % 997) + 1)

        token_type = "PAYLOAD"
        states = {number: {} for number in range(50)}
        callbacks = {}
        model_stack = list(range(50))
        reduce_action = object()

        for index in range(28):
            size = ((seed >> (index % 19)) + index * index + 3 * index) % 4
            current_state = model_stack[-1]
            rule = _Rule("node_" + str(index), size)
            states[current_state][token_type] = (reduce_action, rule)

            if size:
                del model_stack[-size:]
            base_state = model_stack[-1]
            next_state = 1000 + index * 7 + (seed % 5)
            states.setdefault(base_state, {})[rule.origin.name] = (Shift, next_state)
            states[next_state] = {}
            model_stack.append(next_state)

            def reduce_values(items, salt=index):
                weighted = sum((offset + 3) * item for offset, item in enumerate(items))
                return (
                    weighted * (salt + 11)
                    + salt * salt
                    + len(items) * 17
                    + (seed % (salt + 23))
                ) % 100003

            callbacks[rule] = reduce_values

        final_state = 5000 + (seed % 97)
        states[model_stack[-1]][token_type] = (Shift, final_state)
        states[final_state] = {}

        parse_conf = SimpleNamespace(
            states=states,
            end_state=-1,
            callbacks=callbacks,
        )
        parser_state = ParserState(
            parse_conf,
            lexer=None,
            state_stack=list(range(50)),
            value_stack=initial_values,
        )

        result = parser_state.feed_token(Token(token_type, "generated"))

        self.assertIsNone(result)
        self.assertEqual(len(parser_state.state_stack), len(parser_state.value_stack) + 1)
        self.assertEqual(parser_state.value_stack[-1].type, token_type)
