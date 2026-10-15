import io
import random
import string
import unittest

from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.formparser import _parse_form_data
from werkzeug.test import create_environ


ALPHABET = string.ascii_letters + string.digits + " -_."


def _payload(rng, n):
    return "".join(rng.choice(ALPHABET) for _ in range(n)).encode("ascii")


def _build_body(boundary, parts):
    out = io.BytesIO()
    for kind, name, payload, ctype in parts:
        out.write(b"--" + boundary + b"\r\n")
        if kind == "file":
            out.write(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{name}.bin"\r\n'.encode()
            )
        else:
            out.write(f'Content-Disposition: form-data; name="{name}"\r\n'.encode())
        if ctype is not None:
            out.write(f"Content-Type: {ctype}\r\n".encode())
        out.write(b"\r\n")
        out.write(payload)
        out.write(b"\r\n")
    out.write(b"--" + boundary + b"--\r\n")
    return out.getvalue()


def _run(boundary, parts, **kwargs):
    body = _build_body(boundary, parts)
    environ = create_environ(
        method="POST",
        input_stream=io.BytesIO(body),
        content_type="multipart/form-data; boundary=" + boundary.decode(),
        content_length=len(body),
    )
    stream, form, files = _parse_form_data(environ, **kwargs)
    for storage in files.values():
        storage.close()
    return stream, form, files


class MultipartStateTest(unittest.TestCase):
    def test_small_fields_with_limit(self):
        rng = random.Random(11)
        parts = [
            ("field", f"f{i}", _payload(rng, rng.randint(3, 40)), None)
            for i in range(rng.randint(5, 8))
        ]
        _, form, files = _run(b"bndA", parts, max_form_memory_size=4096)
        self.assertEqual(len(form), len(parts))
        self.assertEqual(len(files), 0)

    def test_small_fields_without_limit(self):
        rng = random.Random(12)
        parts = [
            ("field", f"g{i}", _payload(rng, rng.randint(50, 90)), None)
            for i in range(6)
        ]
        _, form, _ = _run(b"bndB", parts)
        self.assertEqual(len(form), 6)

    def test_mixed_fields_and_files(self):
        rng = random.Random(13)
        parts = []
        for i in range(10):
            kind = "file" if rng.random() < 0.4 else "field"
            ctype = "application/octet-stream" if kind == "file" else None
            parts.append((kind, f"m{i}", _payload(rng, rng.randint(1, 120)), ctype))
        _, form, files = _run(b"bndC", parts, max_form_memory_size=10000)
        self.assertEqual(len(form) + len(files), len(parts))

    def test_charset_fields(self):
        rng = random.Random(14)
        charsets = ["latin-1", "iso-8859-1", "ascii", "utf-16", "UTF-8"]
        parts = [
            (
                "field",
                f"c{i}",
                _payload(rng, rng.randint(10, 30)),
                f"text/plain; charset={cs}",
            )
            for i, cs in enumerate(charsets)
        ]
        _, form, _ = _run(b"bndD", parts, max_form_memory_size=2000)
        self.assertEqual(len(form), len(charsets))

    def test_large_field_spanning_chunks(self):
        rng = random.Random(15)
        big = _payload(rng, 65536 + rng.randint(1000, 9000))
        parts = [
            ("field", "pre", _payload(rng, rng.randint(5, 25)), None),
            ("field", "big", big, None),
            ("field", "post", _payload(rng, rng.randint(5, 25)), None),
        ]
        _, form, _ = _run(b"bndE", parts, max_form_memory_size=200000)
        self.assertEqual(len(form["big"]), len(big))

    def test_two_large_fields(self):
        rng = random.Random(16)
        sizes = [40000 + rng.randint(0, 30000) for _ in range(3)]
        parts = [("field", f"L{i}", _payload(rng, n), None) for i, n in enumerate(sizes)]
        _, form, _ = _run(b"bndF", parts, max_form_memory_size=300000)
        self.assertEqual(sum(len(v) for v in form.values()), sum(sizes))

    def test_large_file_then_field(self):
        rng = random.Random(17)
        parts = [
            ("file", "upl", _payload(rng, 70000 + rng.randint(0, 5000)), "text/plain"),
            ("field", "after", _payload(rng, rng.randint(20, 60)), None),
        ]
        _, form, files = _run(b"bndG", parts, max_form_memory_size=100000)
        self.assertEqual(len(files), 1)
        self.assertEqual(len(form), 1)

    def test_field_exceeds_limit(self):
        rng = random.Random(18)
        limit = 70000 + rng.randint(0, 3000)
        parts = [
            ("field", "ok", _payload(rng, rng.randint(30, 70)), None),
            ("field", "huge", _payload(rng, limit + rng.randint(20000, 30000)), None),
        ]
        with self.assertRaises(RequestEntityTooLarge):
            _run(b"bndH", parts, max_form_memory_size=limit, silent=False)

    def test_empty_values(self):
        rng = random.Random(19)
        parts = []
        for i in range(8):
            n = 0 if i % 3 == 0 else rng.randint(1, 9)
            parts.append(("field", f"e{i}", _payload(rng, n), None))
        _, form, _ = _run(b"bndI", parts, max_form_memory_size=500)
        self.assertEqual(len(form), 8)

    def test_files_only(self):
        rng = random.Random(20)
        parts = [
            ("file", f"u{i}", _payload(rng, rng.randint(100, 3000)), "image/png")
            for i in range(4)
        ]
        _, form, files = _run(b"bndJ", parts, max_form_memory_size=20000)
        self.assertEqual(len(files), 4)
        self.assertEqual(len(form), 0)

    def test_repeated_names(self):
        rng = random.Random(21)
        parts = [
            ("field", "dup", _payload(rng, rng.randint(1, 200)), None)
            for _ in range(rng.randint(6, 9))
        ]
        _, form, _ = _run(b"bndK", parts, max_form_memory_size=4000)
        self.assertEqual(len(form.getlist("dup")), len(parts))

    def test_boundary_like_content(self):
        rng = random.Random(22)
        parts = []
        for i in range(5):
            payload = _payload(rng, rng.randint(5, 15)) + b"\r\n--bnd" + _payload(rng, 4)
            parts.append(("field", f"b{i}", payload, None))
        _, form, _ = _run(b"bndLZ", parts, max_form_memory_size=1000)
        self.assertEqual(len(form), 5)
