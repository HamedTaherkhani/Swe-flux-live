import json
import random
import unittest

from haystack.components.converters import JSONConverter
from haystack.dataclasses import ByteStream


class TestJSONConverterLoopDynamics(unittest.TestCase):
    def _run_case(
        self,
        *,
        seed: int,
        source_count: int,
        floor: int,
        span: int,
        field_count: int,
        variant: int,
    ) -> None:
        rng = random.Random(seed)
        fields = {f"meta_{index}" for index in range(field_count)}
        sources = []

        for source_index in range(source_count):
            record_count = floor + rng.randrange(span) + source_index * (1 + seed % 3)
            records = []
            for record_index in range(record_count):
                selector = (
                    rng.randrange(97)
                    + record_index * (variant + 1)
                    + source_index * (seed % 7 + 1)
                ) % 17
                if selector == 0:
                    records.append(f"scalar-{seed}-{source_index}-{record_index}")
                elif selector in {1, 2}:
                    records.append({"other": selector, "position": record_index})
                elif selector == 3:
                    records.append({"payload": [record_index, selector]})
                else:
                    record = {
                        "payload": f"text-{seed ^ (record_index * 31 + source_index)}",
                        "position": record_index,
                    }
                    for field_index in range(field_count + variant % 3):
                        record[f"meta_{field_index}"] = (
                            rng.randrange(10_000) ^ (record_index << (field_index % 4))
                        )
                    records.append(record)

            encoded = json.dumps({"records": records}, separators=(",", ":"))
            sources.append(
                ByteStream.from_string(
                    encoded,
                    meta={"file_path": f"/virtual/case_{seed}/source_{source_index}.json"},
                )
            )

        converter = JSONConverter(
            jq_schema=".records[]",
            content_key="payload",
            extra_meta_fields=fields,
        )
        result = converter.run(
            sources=sources,
            meta={"scenario": f"s{seed % 9}", "variant": variant},
        )

        self.assertEqual(set(result), {"documents"})
        self.assertGreater(len(result["documents"]), source_count)
        self.assertTrue(all(document.content is not None for document in result["documents"]))
        self.assertTrue(all("scenario" in document.meta for document in result["documents"]))

    def test_alpha_sparse_metadata(self):
        self._run_case(seed=11, source_count=2, floor=18, span=9, field_count=2, variant=1)

    def test_bravo_three_sources(self):
        self._run_case(seed=23, source_count=3, floor=20, span=11, field_count=3, variant=2)

    def test_charlie_wide_metadata(self):
        self._run_case(seed=37, source_count=2, floor=24, span=13, field_count=7, variant=4)

    def test_delta_empty_metadata_set(self):
        self._run_case(seed=41, source_count=3, floor=17, span=15, field_count=0, variant=5)

    def test_echo_four_sources(self):
        self._run_case(seed=53, source_count=4, floor=16, span=12, field_count=4, variant=3)

    def test_foxtrot_dense_records(self):
        self._run_case(seed=59, source_count=2, floor=29, span=14, field_count=5, variant=6)

    def test_golf_single_metadata_field(self):
        self._run_case(seed=61, source_count=3, floor=21, span=16, field_count=1, variant=7)

    def test_hotel_broad_sources(self):
        self._run_case(seed=67, source_count=4, floor=19, span=10, field_count=6, variant=8)

    def test_india_larger_batches(self):
        self._run_case(seed=71, source_count=2, floor=31, span=17, field_count=8, variant=9)

    def test_juliet_mixed_rejections(self):
        self._run_case(seed=73, source_count=3, floor=23, span=18, field_count=3, variant=11)

    def test_kilo_many_metadata_fields(self):
        self._run_case(seed=83, source_count=2, floor=27, span=19, field_count=9, variant=12)

    def test_lima_long_source_sequence(self):
        self._run_case(seed=89, source_count=4, floor=22, span=20, field_count=5, variant=14)
