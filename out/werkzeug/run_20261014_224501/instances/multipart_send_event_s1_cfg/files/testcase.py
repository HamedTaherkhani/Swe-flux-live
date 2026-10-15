import random
import unittest

from werkzeug.datastructures import Headers
from werkzeug.sansio.multipart import Data
from werkzeug.sansio.multipart import Epilogue
from werkzeug.sansio.multipart import Field
from werkzeug.sansio.multipart import File
from werkzeug.sansio.multipart import MultipartDecoder
from werkzeug.sansio.multipart import MultipartEncoder
from werkzeug.sansio.multipart import Preamble


HEADER_POOL = [
    "Content-Type",
    "content-disposition",
    "X-Trace",
    "CONTENT-DISPOSITION",
    "X-Part-Index",
    "Content-Disposition",
    "X-Checksum",
    "Content-Language",
]


def build_script(seed):
    rng = random.Random(seed)
    script = [Preamble(data=b"preamble-" + str(seed).encode())]
    for idx in range(7):
        n_headers = rng.randint(0, 9)
        headers = Headers()
        for _ in range(n_headers):
            name = rng.choice(HEADER_POOL)
            headers.add(name, f"v{rng.randint(0, 999)}")
        if rng.random() < 0.55:
            script.append(File(name=f"f{idx}", filename=f"n{idx}.bin", headers=headers))
        else:
            script.append(Field(name=f"k{idx}", headers=headers))
        for _ in range(rng.randint(1, 4)):
            size = rng.choice([0, 0, 3, 11, 17])
            script.append(Data(data=bytes(rng.randrange(65, 91) for _ in range(size)), more_data=True))
        if rng.random() < 0.4:
            # Illegal event injected mid-stream: a second preamble.
            script.append(Preamble(data=b"bogus"))
    script.append(Epilogue(data=b""))
    return script


class TestMultipartEncoderScript(unittest.TestCase):
    def test_encode_scripted_stream(self):
        boundary = b"qaBoundary7"
        encoder = MultipartEncoder(boundary)
        chunks = []
        rejected = 0
        for event in build_script(20241015):
            if isinstance(event, Preamble) and event.data == b"bogus":
                with self.assertRaises(ValueError):
                    encoder.send_event(event)
                rejected += 1
                continue
            chunks.append(encoder.send_event(event))
        body = b"".join(chunks)

        decoder = MultipartDecoder(boundary)
        decoder.receive_data(body)
        decoder.receive_data(None)
        parts = 0
        while True:
            ev = decoder.next_event()
            if isinstance(ev, (Field, File)):
                parts += 1
            if isinstance(ev, Epilogue):
                break
        self.assertEqual(parts, 7)
        self.assertGreaterEqual(rejected, 0)
        self.assertTrue(body.endswith(b"--" + boundary + b"--\r\n"))
