import random
import unittest
from unittest.mock import patch

from haystack.components.websearch.serper_dev import SerperDevWebSearch
from haystack.utils import Secret


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestSerperDevRunDataFlow(unittest.TestCase):
    @staticmethod
    def _token(rng, width):
        return "".join(chr(ord("a") + rng.randrange(26)) for _ in range(width))

    def test_generated_response_variants(self):
        rng = random.Random(8675309)
        responses = []
        for batch in range(7):
            organic = [
                {
                    "title": self._token(rng, 8 + (index % 5)),
                    "link": f"https://{self._token(rng, 7)}.example/{batch}/{index}",
                    "snippet": self._token(rng, 18 + ((batch + index) % 9)),
                    "rank": index + 1,
                }
                for index in range(19 + (batch % 4))
            ]
            related = []
            for index in range(23 + batch):
                title = self._token(rng, 9 + ((batch * 3 + index) % 7))
                item = {
                    "title": title,
                    "link": f"https://questions.example/{self._token(rng, 6)}/{index}",
                }
                if (rng.randrange(11) + batch + index) % 4:
                    item["snippet"] = self._token(rng, 14 + (index % 8))
                related.append(item)

            payload = {"organic": organic, "peopleAlsoAsk": related}
            direct_answer = self._token(rng, 21 + batch)
            if batch == 0:
                payload["answerBox"] = {"snippetHighlighted": [direct_answer], "link": organic[0]["link"]}
            elif batch == 1:
                payload["answerBox"] = {"snippetHighlighted": direct_answer, "link": organic[1]["link"]}
            elif batch == 2:
                payload["answerBox"] = {"snippetHighlighted": [], "snippet": direct_answer}
            elif batch == 3:
                payload["answerBox"] = {"snippetHighlighted": None, "answer": direct_answer}
            elif batch == 4:
                payload["answerBox"] = {"snippetHighlighted": 0, "title": direct_answer}
            elif batch == 5:
                payload["answerBox"] = {"snippetHighlighted": []}
            responses.append(payload)

        component = SerperDevWebSearch(api_key=Secret.from_token(self._token(rng, 32)), top_k=None)
        returned = []
        with patch(
            "haystack.components.websearch.serper_dev.requests.post",
            side_effect=[_Response(payload) for payload in responses],
        ) as post:
            for batch, payload in enumerate(responses):
                component.allowed_domains = (
                    [f"{self._token(rng, 5)}.example" for _ in range(2 + batch % 3)] if batch % 2 else None
                )
                query = " ".join(self._token(rng, 4 + (offset % 5)) for offset in range(6 + batch))
                result = component.run(query=query)
                returned.append(result)
                self.assertEqual(result["links"], [item["link"] for item in payload["organic"]])
                self.assertTrue(all(document.content is not None for document in result["documents"]))

        self.assertEqual(post.call_count, len(responses))
        self.assertTrue(all(item["documents"] and item["links"] for item in returned))
