import os
import random
import shutil
import tempfile
import unittest

from werkzeug.exceptions import HTTPException
from werkzeug.test import EnvironBuilder
from werkzeug.utils import send_from_directory

WORDS = ["alpha", "béta", "gamma", "dëlta", "eps", "zëta", "eta"]
EXTS = [".txt", ".tar.gz", ".bin", ".css", ".svgz", ".json", ""]


class SendFromDirectoryMatrixTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wzqa_")
        self.rng = random.Random(4127)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _plan(self, i):
        name = f"{WORDS[(i * 3) % len(WORDS)]}{i}{EXTS[(i * 5) % len(EXTS)]}"
        size = self.rng.randint(1, 40) * (i % 3 + 1)
        exists = i % 5 != 3
        if exists:
            full = os.path.join(self.root, name)
            with open(full, "wb") as f:
                f.write(bytes((i + k) % 256 for k in range(size)))
            os.utime(full, (1_600_000_000 + i * 977, 1_600_000_000 + i * 977))
        request_path = name if i % 9 != 7 else "../" + name

        kwargs = {}
        if i % 4 == 1:
            kwargs["as_attachment"] = True
        if i % 3 == 0:
            kwargs["use_x_sendfile"] = True
        if i % 5 == 4:
            kwargs["mimetype"] = "application/x-custom"
        if i % 2 == 0:
            kwargs["max_age"] = lambda p: (len(os.path.basename(p)) % 3) - 1
        elif i % 7 == 3:
            kwargs["max_age"] = i * 11
        if i % 7 == 2:
            kwargs["etag"] = f"tag{i}"
        elif i % 7 == 5:
            kwargs["etag"] = False
        if i % 6 == 5:
            kwargs["conditional"] = False

        headers = {}
        if i % 4 == 0:
            headers["If-None-Match"] = "*"
        elif i % 4 == 2:
            headers["Range"] = f"bytes={size * 2}-"
        elif i % 8 == 3:
            headers["Range"] = "bytes=0-0"
        return request_path, kwargs, headers

    def test_matrix(self):
        outcomes = []
        for i in range(16):
            request_path, kwargs, headers = self._plan(i)
            env = EnvironBuilder(path="/f", headers=headers).get_environ()
            try:
                rv = send_from_directory(self.root, request_path, env, **kwargs)
            except HTTPException as e:
                outcomes.append(e.code)
                continue
            outcomes.append(rv.status_code)
            rv.close()

        self.assertEqual(len(outcomes), 16)
        self.assertTrue(all(isinstance(c, int) for c in outcomes))
        self.assertGreater(len(set(outcomes)), 2)
