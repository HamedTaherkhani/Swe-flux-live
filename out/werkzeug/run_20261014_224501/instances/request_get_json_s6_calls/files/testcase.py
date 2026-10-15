import json
import random
import unittest

from werkzeug.exceptions import HTTPException
from werkzeug.wrappers.request import Request


MIMETYPES = ["application/json", "text/plain", "application/vnd.api+json"]


def _make_body(rng, idx):
    payload = {"k%d" % j: rng.randint(0, 99) for j in range(rng.randint(1, 3))}
    text = json.dumps(payload)
    if rng.random() < 0.35:
        # corrupt the document by chopping off its tail
        text = text[: rng.randint(1, len(text) - 1)]
    return text


class TestGetJsonCallStructure(unittest.TestCase):
    def test_get_json_sequence(self):
        rng = random.Random(4242)
        outcomes = []
        for idx in range(9):
            mimetype = MIMETYPES[rng.randrange(len(MIMETYPES))]
            body = _make_body(rng, idx)
            request = Request.from_values(
                method="POST", data=body, content_type=mimetype
            )
            for _ in range(rng.randint(2, 4)):
                force = rng.random() < 0.4
                silent = rng.random() < 0.5
                cache = rng.random() < 0.7
                try:
                    rv = request.get_json(force=force, silent=silent, cache=cache)
                except HTTPException as exc:
                    outcomes.append(("err", exc.code))
                else:
                    outcomes.append(("ok", rv is None))
        self.assertGreater(len(outcomes), 20)
        self.assertTrue(any(kind == "err" for kind, _ in outcomes))
        self.assertTrue(any(kind == "ok" for kind, _ in outcomes))


if __name__ == "__main__":
    unittest.main()
