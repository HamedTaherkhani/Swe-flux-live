import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path

from haystack import Document
from haystack.document_stores.in_memory import InMemoryDocumentStore


class TestDocumentStoreLoadCallStructure(unittest.TestCase):
    def test_repeated_loads_with_mixed_documents(self):
        rng = random.Random("repo-behave-in-memory-load")
        index_name = "qa-" + hashlib.sha256(str(rng.getrandbits(256)).encode()).hexdigest()
        blueprint = InMemoryDocumentStore(index=index_name)

        initial_ids = [
            hashlib.sha256(f"initial:{position}:{rng.getrandbits(96)}".encode()).hexdigest()
            for position in range(28)
        ]
        initial_documents = []
        for position, document_id in enumerate(initial_ids):
            token_count = 3 + rng.randrange(9)
            words = [
                f"term{(rng.randrange(97) + position * (offset + 1)) % 101}"
                for offset in range(token_count)
            ]
            content = None if rng.randrange(11) == 0 else " ".join(words)
            initial_documents.append(
                Document(id=document_id, content=content, meta={"phase": "initial", "rank": position})
            )

        overlap_ids = rng.sample(initial_ids, 21)
        new_ids = [
            hashlib.sha256(f"later:{position}:{rng.getrandbits(96)}".encode()).hexdigest()
            for position in range(23)
        ]
        later_ids = overlap_ids + new_ids
        rng.shuffle(later_ids)

        later_documents = []
        for position, document_id in enumerate(later_ids):
            token_count = 2 + ((rng.randrange(17) * (position + 3)) % 13)
            words = [
                f"token{(rng.randrange(149) ^ (position * 7 + offset * 11)) % 157}"
                for offset in range(token_count)
            ]
            content = None if (rng.randrange(7) + position) % 6 == 0 else " ".join(words)
            later_documents.append(
                Document(id=document_id, content=content, meta={"phase": "later", "rank": position})
            )

        def payload(documents):
            data = blueprint.to_dict()
            data["documents"] = [document.to_dict(flatten=False) for document in documents]
            return data

        loaded_first = None
        loaded_second = None
        try:
            with tempfile.TemporaryDirectory() as directory:
                first_path = Path(directory) / "first.json"
                second_path = Path(directory) / "second.json"
                first_path.write_text(json.dumps(payload(initial_documents)), encoding="utf-8")
                second_path.write_text(json.dumps(payload(later_documents)), encoding="utf-8")

                loaded_first = InMemoryDocumentStore.load_from_disk(str(first_path))
                self.assertEqual(loaded_first.count_documents(), len(set(initial_ids)))

                loaded_second = InMemoryDocumentStore.load_from_disk(str(second_path))
                expected_ids = set(initial_ids) | set(new_ids)
                self.assertEqual(loaded_second.count_documents(), len(expected_ids))
                self.assertEqual(set(loaded_second.storage), expected_ids)
                self.assertTrue(all(loaded_second.storage[item.id].meta == item.meta for item in later_documents))
        finally:
            blueprint.shutdown()
            if loaded_first is not None:
                loaded_first.shutdown()
            if loaded_second is not None:
                loaded_second.shutdown()
