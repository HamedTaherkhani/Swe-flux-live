import random
import unittest
from types import SimpleNamespace

from haystack.components.converters.azure import AzureOCRDocumentConverter
from haystack.dataclasses import ByteStream


class _Poller:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class _Client:
    def __init__(self, result):
        self._result = result

    def begin_analyze_document(self, **kwargs):
        assert kwargs["document"]
        return _Poller(self._result)


class _Result:
    def __init__(self, pages, tables):
        self.pages = pages
        self.tables = tables

    def to_dict(self):
        return {"pages": len(self.pages), "tables": len(self.tables)}


def _build_result():
    rng = random.Random(731_947)
    pages = []
    tables = []

    for page_number, line_count in enumerate((47, 43), start=1):
        y = rng.uniform(0.2, 0.7)
        lines = []
        for index in range(line_count):
            y += rng.choice((0.011, 0.019, 0.032, 0.067, 0.091))
            x = rng.uniform(0.1, 7.4)
            offset = page_number * 10_000 + index * 23
            span = SimpleNamespace(offset=offset, length=7)
            polygon = ((x, y), (x + 0.4, y), (x + 0.4, y + 0.02), (x, y + 0.02))
            lines.append(SimpleNamespace(content=f"p{page_number}-token-{index:02d}", polygon=polygon, spans=[span]))

            if rng.randrange(13) in (2, 5, 11):
                tables.append(
                    SimpleNamespace(
                        bounding_regions=[SimpleNamespace(page_number=page_number)],
                        spans=[SimpleNamespace(offset=offset - 1, length=9)],
                    )
                )

        rng.shuffle(lines)
        pages.append(SimpleNamespace(page_number=page_number, lines=lines))

    return _Result(pages, tables)


class TestAzureSingleColumnLoopBehavior(unittest.TestCase):
    def test_seeded_layout_via_run(self):
        result = _build_result()
        converter = AzureOCRDocumentConverter.__new__(AzureOCRDocumentConverter)
        converter.document_analysis_client = _Client(result)
        converter.model_id = "prebuilt-layout"
        converter.store_full_path = False
        converter.page_layout = "single_column"
        converter.threshold_y = 0.05
        converter._convert_tables = lambda *, result, meta: []

        response = converter.run(
            sources=[ByteStream(data=b"deterministic synthetic document", meta={"source": "generated"})],
            meta=[{"suite": "loop-behavior"}],
        )

        self.assertEqual(len(response["documents"]), 1)
        self.assertEqual(len(response["raw_azure_response"]), 1)
        self.assertIsInstance(response["documents"][0].content, str)
        self.assertTrue(response["documents"][0].content)
        self.assertIn("\f", response["documents"][0].content)
        self.assertEqual(response["documents"][0].meta["suite"], "loop-behavior")
