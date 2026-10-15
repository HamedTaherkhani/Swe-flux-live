import random
import unittest
import warnings

from werkzeug.datastructures import Headers
from werkzeug.middleware.lint import GuardedIterator


class _ClosableBody:
    def __init__(self, parts):
        self._parts = list(parts)
        self.closed = False

    def __iter__(self):
        return iter(self._parts)

    def close(self):
        self.closed = True


class GuardedIteratorCloseDataFlowTest(unittest.TestCase):
    def test_close_many_responses(self):
        rng = random.Random(4127)
        statuses = [200, 201, 304, 204, 101, 404, 302, 103, 500]
        meta = ["Content-Type", "content-encoding", "X-Trace", "ETag",
                "Content-Language", "Cache-Control", "Vary"]
        seen_warnings = 0
        guards = []
        for idx in range(36):
            n_parts = rng.randrange(0, 4)
            parts = [b"x" * rng.randrange(0, 7) for _ in range(n_parts)]
            body = _ClosableBody(parts) if rng.random() < 0.5 else list(parts)
            if idx % 7 == 3:
                headers_set = ()
            else:
                status = statuses[(idx * 5 + rng.randrange(3)) % len(statuses)]
                headers = Headers()
                for name in rng.sample(meta, rng.randrange(0, 4)):
                    headers.add(name, f"v{rng.randrange(100)}")
                mode = rng.randrange(4)
                total = sum(len(p) for p in parts)
                if mode == 1:
                    headers.add("Content-Length", str(total))
                elif mode == 2:
                    headers.add("Content-Length", str(total + rng.randrange(1, 5)))
                elif mode == 3:
                    headers.add("Content-Length", "n/a" if idx % 2 else "0")
                headers_set = (status, headers)
            chunks = []
            guard = GuardedIterator(body, headers_set, chunks)
            consume = rng.randrange(0, n_parts + 1)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                for _ in range(consume):
                    next(guard)
                guard.close()
            seen_warnings += len(caught)
            self.assertTrue(guard.closed)
            self.assertEqual(len(chunks), consume)
            if isinstance(body, _ClosableBody):
                self.assertTrue(body.closed)
            guards.append(guard)
        self.assertEqual(len(guards), 36)
        self.assertGreater(seen_warnings, 0)


if __name__ == "__main__":
    unittest.main()
