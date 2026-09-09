import random
import string
import unittest

from fastapi.sse import format_sse_event


class TestFormatSSEEventCalls(unittest.TestCase):
    @staticmethod
    def _multiline_value(
        rng: random.Random, line_count: int, salt: int
    ) -> str:
        alphabet = string.ascii_letters + string.digits
        pieces: list[str] = []
        terminators = ("\n", "\r\n", "\r")
        for position in range(line_count):
            width = 5 + ((position * 7 + salt + rng.randrange(11)) % 19)
            token = "".join(rng.choice(alphabet) for _ in range(width))
            pieces.append(f"{position:x}-{token}")
            if position + 1 < line_count:
                pieces.append(terminators[(position + salt + rng.randrange(7)) % 3])
        return "".join(pieces)

    def test_seeded_batch_with_multiline_fields(self) -> None:
        rng = random.Random(731_904_267)
        rendered: list[bytes] = []

        for index in range(18):
            data_lines = 19 + ((index * 5 + rng.randrange(13)) % 17)
            comment_lines = 17 + ((index * 3 + rng.randrange(11)) % 15)
            data_str = self._multiline_value(rng, data_lines, index * 2 + 1)
            comment = self._multiline_value(rng, comment_lines, index * 3 + 2)

            event = (
                f"evt-{(index * index + rng.randrange(101)):x}"
                if (index + data_lines) % 4 != 0
                else None
            )
            event_id = (
                f"id-{rng.randrange(10_000, 99_999):x}"
                if (index * 3 + comment_lines) % 5 != 1
                else None
            )
            retry = (
                200 + ((sum(data_str.encode()) + index * 97) % 20_000)
                if (data_lines + comment_lines) % 3 != 0
                else None
            )

            rendered.append(
                format_sse_event(
                    data_str=data_str,
                    event=event,
                    id=event_id,
                    retry=retry,
                    comment=comment,
                )
            )

        self.assertEqual(len(rendered), 18)
        self.assertTrue(all(item.endswith(b"\n\n") for item in rendered))
        self.assertTrue(all(item.startswith(b": ") for item in rendered))
        self.assertGreater(sum(map(len, rendered)), 10_000)
