import random
import unittest
from urllib.parse import quote

from werkzeug.sansio.multipart import Data
from werkzeug.sansio.multipart import Epilogue
from werkzeug.sansio.multipart import Field
from werkzeug.sansio.multipart import File
from werkzeug.sansio.multipart import MultipartDecoder
from werkzeug.sansio.multipart import NeedData
from werkzeug.sansio.multipart import Preamble

SYLLABLES = ["ka", "zu", "mo", "ri", "te", "xo", "lu", "ne", "pa", "vi"]
EXTS = ["txt", "bin", "csv", "png"]
ACCENTED = ["é", "ü", "€", "ñ"]


def _word(rng, n):
    return "".join(rng.choice(SYLLABLES) for _ in range(n))


def _build_part(rng, index):
    nl = rng.choice(["\r\n", "\n"])
    name = _word(rng, 2 + index % 3) + str(index * 7 % 5)
    params = [f'name="{name}"']
    kind = index % 4
    if kind == 1:
        params.append(f'filename="{_word(rng, 2)}.{rng.choice(EXTS)}"')
    elif kind == 2:
        raw = _word(rng, 1) + rng.choice(ACCENTED) + _word(rng, 1)
        params.append("filename*=UTF-8''" + quote(raw) + "." + rng.choice(EXTS))
    elif kind == 3:
        params.append(f'filename="{_word(rng, 1)}%22{_word(rng, 1)}"')
    if rng.random() < 0.5:
        params.insert(0, f"tag={_word(rng, 1).upper()}")
    sep = rng.choice(["; ", ";", " ;\t"])
    value = "form-data" + sep + sep.join(params)
    lines = []
    if rng.random() < 0.5:
        # split the disposition header with a continuation line
        cut = value.index(";") + 1
        lines.append("Content-Disposition:" + value[:cut])
        lines.append(rng.choice([" ", "\t"]) + value[cut:].lstrip())
    else:
        lines.append("Content-Disposition: " + value)
    if rng.random() < 0.6:
        lines.append(f"X-Seq:\t {index * 13 % 9}  ")
    head = nl.join(lines) + nl + nl
    body = "".join(rng.choice("abcdef\n-") for _ in range(rng.randint(3, 30)))
    return head + body, nl


class TestMultipartNextEventState(unittest.TestCase):
    def test_chunked_decode(self):
        rng = random.Random(4127)
        boundary = "b" + _word(rng, 3)
        pieces = ["junk-preamble"]
        last_nl = "\r\n"
        for i in range(9):
            part, nl = _build_part(rng, i)
            pieces.append(f"{last_nl}--{boundary}{nl}{part}")
            last_nl = nl
        pieces.append(f"{last_nl}--{boundary}--{last_nl}trailing")
        payload = "".join(pieces).encode()

        decoder = MultipartDecoder(boundary.encode())
        events = []
        pos = 0
        while pos < len(payload):
            size = rng.randint(1, 23)
            decoder.receive_data(payload[pos : pos + size])
            pos += size
            while True:
                ev = decoder.next_event()
                if isinstance(ev, NeedData):
                    break
                events.append(ev)
        decoder.receive_data(None)
        while not events or not isinstance(events[-1], Epilogue):
            events.append(decoder.next_event())

        self.assertIsInstance(events[0], Preamble)
        parts = [e for e in events if isinstance(e, (Field, File))]
        self.assertEqual(len(parts), 9)
        self.assertGreater(sum(isinstance(e, File) for e in parts), 3)
        self.assertTrue(all(isinstance(e, Data) for e in events[2:3]))
        finals = [e for e in events if isinstance(e, Data) and not e.more_data]
        self.assertEqual(len(finals), 9)
