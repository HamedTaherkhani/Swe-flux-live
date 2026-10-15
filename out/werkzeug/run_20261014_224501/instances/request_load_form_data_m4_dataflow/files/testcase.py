import random
import unittest
import warnings
from io import BytesIO
from urllib.parse import urlencode

from werkzeug.datastructures import FileStorage
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.test import create_environ
from werkzeug.test import encode_multipart
from werkzeug.wrappers import Request

BOUNDARY = "qaBoundary7f3c"


def _fields(rng, n):
    return [(f"k{rng.randint(0, 5)}", "v" * rng.randint(1, 9)) for _ in range(n)]


def _urlencoded_environ(pairs, method="POST", **kw):
    body = urlencode(pairs).encode()
    return create_environ(
        method=method,
        input_stream=BytesIO(body),
        content_length=len(body),
        content_type="application/x-www-form-urlencoded",
        **kw,
    )


def _multipart_environ(rng, n_text, n_files):
    values = MultiDict()
    for name, value in _fields(rng, n_text):
        values.add(name, value)
    for i in range(n_files):
        payload = bytes(rng.randint(65, 90) for _ in range(rng.randint(3, 30)))
        values.add(f"f{i % 3}", FileStorage(BytesIO(payload), filename=f"file{i}.bin"))
    boundary, body = encode_multipart(values, boundary=BOUNDARY)
    return create_environ(
        method="POST",
        input_stream=BytesIO(body),
        content_length=len(body),
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def _raw_environ(body, content_type):
    return create_environ(
        method="PUT",
        input_stream=BytesIO(body),
        content_length=len(body),
        content_type=content_type,
    )


class StreamOverrideRequest(Request):
    def _get_stream_for_parsing(self):
        if self._cached_data is not None:
            return BytesIO(self._cached_data)
        return self.stream


class WantParityRequest(Request):
    @property
    def want_form_data_parsed(self):
        return (self.content_length or 0) % 3 == 0


class WantNeverRequest(Request):
    @property
    def want_form_data_parsed(self):
        return False


class WantNeverDictRequest(WantNeverRequest):
    parameter_storage_class = dict


class PickyParseRequest(Request):
    def _parse_form_data(self, stream):
        parsed = super()._parse_form_data(stream)
        form, files = parsed
        if len(form.getlist("k1")) % 2 == 1:
            return None
        return parsed


class PickyStreamRequest(StreamOverrideRequest, PickyParseRequest):
    pass


class LoadFormDataFlowTest(unittest.TestCase):
    def setUp(self):
        self._wctx = warnings.catch_warnings()
        self._wctx.__enter__()
        warnings.simplefilter("ignore", DeprecationWarning)

    def tearDown(self):
        self._wctx.__exit__(None, None, None)

    def test_urlencoded_form_then_files(self):
        rng = random.Random(11)
        total = 0
        for i in range(7):
            req = Request(_urlencoded_environ(_fields(rng, 3 + i)))
            total += len(req.form)
            self.assertEqual(len(req.files), 0)
            self.assertIs(req.values.dicts[1], req.form)
        self.assertGreater(total, 0)

    def test_multipart_files_first(self):
        rng = random.Random(23)
        seen = 0
        for i in range(5):
            req = Request(_multipart_environ(rng, i + 1, (i % 3) + 1))
            seen += len(list(req.files.items(multi=True)))
            _ = req.form
            _ = req.files
            req.close()
        self.assertGreater(seen, 0)

    def test_repeated_uncached_get_data(self):
        rng = random.Random(37)
        for i in range(4):
            req = Request(_urlencoded_environ(_fields(rng, 2 * i + 1)))
            for _ in range(rng.randint(2, 6)):
                self.assertEqual(req.get_data(cache=False, parse_form_data=True), b"")
            self.assertTrue(req.form)

    def test_data_property_non_form_body(self):
        rng = random.Random(41)
        for i in range(6):
            body = bytes(rng.randint(97, 122) for _ in range(5 + 3 * i))
            req = Request(_raw_environ(body, "application/octet-stream"))
            self.assertEqual(req.data, body)
            self.assertEqual(req.data, body)
            self.assertEqual(len(req.form), 0)

    def test_cached_body_then_form(self):
        rng = random.Random(53)
        for i in range(5):
            req = Request(_urlencoded_environ(_fields(rng, 4 + i)))
            raw = req.get_data()
            self.assertTrue(raw)
            self.assertTrue(req.form)
            self.assertEqual(len(req.files), 0)

    def test_stream_override(self):
        rng = random.Random(67)
        for i in range(6):
            if i % 2:
                req = StreamOverrideRequest(_multipart_environ(rng, 2, 1 + i // 2))
                _ = req.files
            else:
                req = StreamOverrideRequest(_urlencoded_environ(_fields(rng, 3 + i)))
                req.get_data()
                _ = req.form
            _ = req.form
            req.close()
        self.assertIsInstance(req.form, MultiDict)

    def test_want_never(self):
        rng = random.Random(71)
        for i in range(4):
            req = WantNeverRequest(_urlencoded_environ(_fields(rng, 2 + i)))
            self.assertEqual(len(req.form), 0)
            self.assertEqual(len(req.files), 0)
            req.get_data(cache=False, parse_form_data=True)

    def test_want_never_dict_storage(self):
        rng = random.Random(79)
        for i in range(3):
            req = WantNeverDictRequest(_multipart_environ(rng, 1 + i, 1))
            self.assertIsInstance(req.files, dict)
            self.assertIsInstance(req.form, dict)
            req.close()

    def test_want_parity(self):
        rng = random.Random(83)
        parsed = 0
        for i in range(9):
            req = WantParityRequest(_urlencoded_environ(_fields(rng, 1 + i)))
            for _ in range(3):
                req.get_data(cache=False, parse_form_data=True)
            parsed += "form" in req.__dict__
        self.assertGreater(parsed, 0)

    def test_picky_parse(self):
        rng = random.Random(97)
        for i in range(10):
            req = PickyParseRequest(_urlencoded_environ(_fields(rng, 3 + i)))
            _ = req.form
            _ = req.files
            _ = req.values

    def test_picky_stream_combo(self):
        rng = random.Random(101)
        for i in range(7):
            req = PickyStreamRequest(_urlencoded_environ(_fields(rng, 2 + 2 * i)))
            if i % 3 == 0:
                req.get_data(cache=False, parse_form_data=True)
            _ = req.files

    def test_size_limits(self):
        rng = random.Random(113)
        raised = 0
        for i in range(6):
            req = Request(_multipart_environ(rng, 2 + 2 * i, 0))
            if i % 2:
                req.max_content_length = 300 + 40 * i
            else:
                req.max_form_parts = 5 + i
            for _ in range(2):
                try:
                    _ = req.form
                except RequestEntityTooLarge:
                    raised += 1
        self.assertGreater(raised, 0)

    def test_get_method_values(self):
        rng = random.Random(127)
        for i in range(5):
            req = Request(_urlencoded_environ(_fields(rng, 2 + i), method="GET"))
            self.assertEqual(len(req.values.dicts), 1)
            if i % 2:
                self.assertTrue(req.form)
