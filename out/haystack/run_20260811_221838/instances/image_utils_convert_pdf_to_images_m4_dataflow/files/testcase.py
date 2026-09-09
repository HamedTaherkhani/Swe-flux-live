import random
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from haystack.components.converters.image.image_utils import (
    _batch_convert_pdf_pages_to_images as batch_convert,
)


class _FakeImage:
    mode = "RGB"
    info = {}

    def __init__(self, token):
        self.token = token
        self.thumbnail_calls = []

    def thumbnail(self, *, size, reducing_gap):
        self.thumbnail_calls.append((size, reducing_gap))

    def save(self, stream, format):
        stream.write(f"{format}:{self.token}".encode())


class _FakeBitmap:
    def __init__(self, token):
        self.image = _FakeImage(token)
        self.closed = False

    def to_pil(self):
        return self.image

    def close(self):
        self.closed = True


class _FakePage:
    def __init__(self, seed, index):
        self.seed = seed
        self.index = index

    def get_mediabox(self):
        if (self.seed * 5 + self.index * 7) % 4 == 0:
            width, height = 36 + self.index % 9, 52 + self.seed % 11
        else:
            width, height = 380 + (self.seed * 13 + self.index * 17) % 170, 610 + self.index % 130
        return 0, 0, width, height

    def render(self, *, scale):
        return _FakeBitmap((self.seed * 1009 + self.index * 37 + int(scale * 1000)) % 100003)


class _FakePdfDocument:
    def __init__(self, stream):
        payload = stream.read().decode()
        if payload.startswith("broken"):
            raise RuntimeError("synthetic unreadable document")
        seed_text, count_text = payload.split(":")
        self.seed = int(seed_text)
        self.count = int(count_text)
        self.closed = False

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        return _FakePage(self.seed, index)

    def close(self):
        self.closed = True


class _FakePILModule:
    MAX_IMAGE_PIXELS = 120_000


class TestConvertPdfToImagesDataFlow(TestCase):
    def _exercise(self, documents, *, return_base64=False, size=None, expect_lookup_error=False):
        with TemporaryDirectory() as directory:
            infos = []
            expected_doc_ids = set()
            for file_index, (seed, page_count, requested_pages) in enumerate(documents):
                path = Path(directory) / f"generated_{file_index}_{seed}.pdf"
                payload = "broken-data" if page_count is None else f"{seed}:{page_count}"
                path.write_text(payload, encoding="utf-8")
                for item_index, page_number in enumerate(requested_pages):
                    doc_idx = seed * 1000 + file_index * 100 + item_index
                    infos.append({"doc_idx": doc_idx, "path": path, "page_number": page_number})
                    expected_doc_ids.add(doc_idx)

            with ExitStack() as stack:
                stack.enter_context(
                    patch("haystack.components.converters.image.image_utils.PdfDocument", _FakePdfDocument)
                )
                stack.enter_context(patch("haystack.components.converters.image.image_utils.PILImage", _FakePILModule))
                stack.enter_context(
                    patch("haystack.components.converters.image.image_utils.pypdfium2_import.check")
                )
                stack.enter_context(patch("haystack.components.converters.image.image_utils.pillow_import.check"))
                if expect_lookup_error:
                    with self.assertRaises(KeyError):
                        batch_convert(pdf_page_infos=infos, return_base64=return_base64, size=size)
                else:
                    result = batch_convert(pdf_page_infos=infos, return_base64=return_base64, size=size)
                    self.assertEqual(set(result), expected_doc_ids)
                    self.assertTrue(all(isinstance(value, str) for value in result.values()) if return_base64 else result)

    @staticmethod
    def _pages(seed, count, page_count, *, duplicates=False):
        rng = random.Random(seed)
        pages = [rng.randrange(1, page_count + 1) for _ in range(count)]
        if not duplicates:
            pages = list(range(1, min(count, page_count) + 1))
            rng.shuffle(pages)
        return pages

    def test_dense_ascending_pages(self):
        self._exercise([(11, 19, self._pages(101, 18, 19))])

    def test_seeded_duplicate_pages(self):
        self._exercise([(17, 14, self._pages(203, 27, 14, duplicates=True))])

    def test_resized_page_sweep(self):
        self._exercise([(23, 22, self._pages(307, 20, 22))], size=(73, 91))

    def test_base64_duplicate_mix(self):
        self._exercise(
            [(29, 18, self._pages(409, 24, 18, duplicates=True))],
            return_base64=True,
        )

    def test_three_grouped_documents(self):
        self._exercise(
            [
                (31, 12, self._pages(503, 10, 12)),
                (37, 15, self._pages(509, 13, 15)),
                (41, 11, self._pages(521, 9, 11)),
            ]
        )

    def test_many_reordered_pages(self):
        self._exercise([(43, 25, self._pages(601, 23, 25))])

    def test_alternating_scale_pressure(self):
        pages = self._pages(701, 21, 21)
        pages = pages[::2] + pages[1::2]
        self._exercise([(47, 21, pages)])

    def test_resized_base64_across_files(self):
        self._exercise(
            [
                (53, 13, self._pages(809, 16, 13, duplicates=True)),
                (59, 17, self._pages(811, 19, 17, duplicates=True)),
            ],
            return_base64=True,
            size=(64, 88),
        )

    def test_zero_page_is_skipped(self):
        pages = self._pages(907, 18, 16, duplicates=True)
        pages.insert(len(pages) // 3, 0)
        self._exercise([(61, 16, pages)], expect_lookup_error=True)

    def test_oversized_page_is_skipped(self):
        pages = self._pages(1009, 17, 15, duplicates=True)
        pages.insert(len(pages) // 2, 22)
        self._exercise([(67, 15, pages)], expect_lookup_error=True)

    def test_empty_document(self):
        self._exercise([(71, 0, [1])], expect_lookup_error=True)

    def test_unreadable_document(self):
        self._exercise([(73, None, [1])], return_base64=True, expect_lookup_error=True)
