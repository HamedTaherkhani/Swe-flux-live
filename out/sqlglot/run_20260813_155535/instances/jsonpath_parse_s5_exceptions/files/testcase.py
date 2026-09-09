import unittest

from sqlglot.jsonpath import parse


class TestJSONPathParseExceptions(unittest.TestCase):
    def test_generated_path_with_terminal_separator(self):
        state = sum((index + 1) * ord(character) for index, character in enumerate("jsonpath"))
        segments = []

        for index in range(ord("z") - ord("a")):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            value = (state >> 9) % 97
            choice = state % 5

            if choice == 0:
                segments.append(f".field_{index}_{value}")
            elif choice == 1:
                segments.append(f"[{value}]")
            elif choice == 2:
                segments.append(f"['key_{index}_{value}']")
            elif choice == 3:
                segments.append(f"..branch_{index}_{value}")
            else:
                segments.append(f"[{value}:{value + 3}:{state % 4 + 1}]")

        path = "$" + "".join(segments) + chr(ord("0") - 2)
        escaped = None

        try:
            parse(path)
        except BaseException as exc:
            escaped = exc

        self.assertIsNotNone(escaped)
        self.assertGreater(len(str(escaped)), len(path))
        self.assertEqual(str(escaped).count(path), 1)
