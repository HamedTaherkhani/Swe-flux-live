import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from haystack.components.converters.azure import AzureOCRDocumentConverter
from haystack.dataclasses import ByteStream
from haystack.utils import Secret


def _span(offset, length=1):
    return SimpleNamespace(offset=offset, length=length)


def _build_result():
    rng = random.Random(94721)
    pages = []
    for page_number in range(1, 3):
        lines = []
        for index in range(28):
            offset = (page_number - 1) * 900 + index * 31
            token = (rng.randrange(1000, 9000) * (index + page_number)) % 9973
            lines.append(
                SimpleNamespace(
                    content=f"line-{page_number}-{index}-{token:x}",
                    spans=[_span(offset, 9 + index % 5)],
                )
            )
        pages.append(SimpleNamespace(page_number=page_number, lines=lines))

    tables = []
    for table_number in range(3):
        has_caption = table_number % 2 == 0
        row_count = 7 if has_caption else 6
        column_count = 4
        row_shift = int(has_caption)
        cells = []

        if has_caption:
            caption_code = rng.randrange(10_000, 99_999) ^ (table_number + 17) ** 3
            cells.append(
                SimpleNamespace(
                    content=f":selected:cap-{caption_code:x}",
                    column_span=column_count,
                    row_span=1,
                    row_index=0,
                    column_index=0,
                    kind="content",
                )
            )

        rolling = rng.randrange(200, 800)
        for logical_row in range(6):
            for column in range(column_count):
                rolling = (rolling * 37 + rng.randrange(11, 997) + logical_row * 13 + column) % 10007
                marker = ":unselected:" if (rolling + column) % 5 == 0 else ""
                kind = "columnHeader" if logical_row < 2 else "content"
                cells.append(
                    SimpleNamespace(
                        content=f"{marker}c{table_number}-{logical_row}-{column}-{rolling:x}",
                        column_span=1,
                        row_span=1,
                        row_index=logical_row + row_shift,
                        column_index=column,
                        kind=kind,
                    )
                )

        start_offset = 205 + table_number * 317
        if table_number == 1:
            regions = []
        elif table_number == 2:
            regions = [SimpleNamespace(page_number=1), SimpleNamespace(page_number=2)]
        else:
            regions = [SimpleNamespace(page_number=1)]
        tables.append(
            SimpleNamespace(
                column_count=column_count,
                row_count=row_count,
                cells=cells,
                bounding_regions=regions,
                spans=[_span(start_offset, 126 + table_number * 19)],
            )
        )

    result = SimpleNamespace(tables=tables, pages=pages, paragraphs=[])
    result.to_dict = lambda: {
        "table_count": len(tables),
        "cell_count": sum(len(table.cells) for table in tables),
    }
    return result


class TestAzureConvertTablesState(unittest.TestCase):
    def test_run_with_generated_tables(self):
        result = _build_result()
        poller = SimpleNamespace(result=lambda: result)
        source_data = bytes((index * index + 19 * index + 23) % 251 for index in range(193))
        source = ByteStream(data=source_data, meta={"file_path": "generated-input.bin", "batch": 7})

        with patch("haystack.components.converters.azure.DocumentAnalysisClient") as client_type:
            client_type.return_value.begin_analyze_document.return_value = poller
            converter = AzureOCRDocumentConverter(
                endpoint="https://example.invalid",
                api_key=Secret.from_token("not-a-real-key"),
                preceding_context_len=4,
                following_context_len=5,
            )
            output = converter.run(sources=[source], meta=[{"series": sum(source_data) % 101}])

        documents = output["documents"]
        self.assertEqual(len(documents), len(result.tables) + 1)
        self.assertTrue(all(doc.content for doc in documents[:-1]))
        self.assertEqual(len(output["raw_azure_response"]), 1)
        self.assertTrue(all("preceding_context" in doc.meta for doc in documents[:-1]))
