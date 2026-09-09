"""Deterministic direct exercise of ``kedro.utils._parse_filepath``.

Builds a table of filepaths programmatically (local POSIX paths, Windows
drive-letter paths, HTTP(S) URLs, file:// URLs including Windows-style
targets, cloud-storage URLs with assorted netloc/username/port/query/
fragment combinations, and a non-cloud scheme carrying a netloc) and calls
the target function directly, once per constructed input, so that its
conditional branches fire in many different combinations across the run.
"""

import unittest

from kedro.utils import _parse_filepath


def _build_filepaths():
    """Construct the per-call filepath inputs programmatically."""
    sep = "://"  # protocol delimiter
    paths = []

    # Local paths with no URL scheme at all.
    for name in ["events_alpha", "events_beta", "events_gamma"]:
        paths.append("/".join(["", "data", "raw", name + ".csv"]))
    paths.append(".".join(["notes", "md"]))

    # Windows drive-letter paths, backslash and forward-slash flavours.
    for drive, leaf in [("C", "in"), ("D", "out"), ("E", "tmp")]:
        paths.append(drive + ":" + "\\" + "\\".join(["work", leaf + ".csv"]))
    paths.append("F" + ":" + "/" + "forward" + "/" + "slash.csv")

    # HTTP(S) URLs, one of them carrying a query string.
    for scheme, host, tail in [
        ("http", "example.com", "data/x.csv"),
        ("https", "example.com:8081", "a/b.csv?download=1"),
        ("http", "localhost:9000", "y.csv"),
    ]:
        paths.append(scheme + sep + host + "/" + tail)

    # file:// URLs, including Windows-style targets (':' and '|' separators)
    # and one with a non-empty netloc that is not a cloud protocol.
    paths.append("file" + sep + "/" + "/".join(["", "tmp", "local", "data.csv"]))
    paths.append("file" + sep + "/C:" + "/".join(["", "data", "win.csv"]))
    paths.append("file" + sep + "/D|" + "/".join(["", "alt", "win.csv"]))
    paths.append("file" + sep + "localhost" + "/".join(["", "etc", "hosts"]))

    # Cloud-storage URLs exercising netloc/username/port/query/fragment
    # combinations.  Tuples: (scheme, netloc, key, query, fragment).
    cloud_cases = [
        ("s3", "bucket", "data/file.csv", "", ""),
        ("s3", "host.example:9000", "data/file.csv", "", ""),
        ("s3a", "bucket", "key.csv", "versionId=v9", ""),
        ("gcs", "bucket", "key.csv", "", "frag"),
        ("s3n", "bucket", "k.csv", "a=1&b=2", "sec"),
        ("abfss", "container@account.dfs.core.windows.net", "dir/file.csv", "", ""),
        ("oci", "bucket@namespace", "path/to/object", "", ""),
        ("abfss", "account.dfs.core.windows.net", "dir/file.csv", "", ""),
        ("adl", "store.azuredatalake.net", "folder/f.csv", "", ""),
        ("gdrive", "folderid", "doc", "", ""),
        ("oss", "bucket@endpoint", "object", "", ""),
        ("abfs", "container@account", "file", "", ""),
        ("gs", "bucket", "obj.csv", "gen=3", ""),
        ("oci", "bucket@namespace", "o.csv", "", "part2"),
    ]
    for scheme, netloc, key, query, fragment in cloud_cases:
        url = scheme + sep + netloc + "/" + key
        if query:
            url += "?" + query
        if fragment:
            url += "#" + fragment
        paths.append(url)

    # A non-cloud scheme that still carries a netloc.
    paths.append("ftp" + sep + "example.com" + "/pub/file.csv")

    return paths


class TestParseFilepathDataFlow(unittest.TestCase):
    def test_traced_run(self):
        paths = _build_filepaths()
        results = [_parse_filepath(p) for p in paths]

        self.assertEqual(len(results), len(paths))
        by_input = dict(zip(paths, results))

        # Every call returns a well-formed two-field mapping.
        for res in results:
            self.assertEqual(set(res), {"protocol", "path"})
            self.assertTrue(res["protocol"])
            self.assertTrue(res["path"])

        # Scheme-less and drive-letter inputs come back as local files,
        # with the path passed through unchanged.
        for p in paths:
            if "://" not in p:
                self.assertEqual(by_input[p]["protocol"], "file")
                self.assertEqual(by_input[p]["path"], p)

        # HTTP(S) inputs keep the full URL as the path.
        for p in paths:
            if p.startswith("http"):
                self.assertEqual(by_input[p]["path"], p)

        # file:// URLs targeting a Windows drive are rewritten to the
        # drive-letter form.
        self.assertTrue(by_input["file:///C:/data/win.csv"]["path"].startswith("C:"))
        self.assertTrue(by_input["file:///D|/alt/win.csv"]["path"].startswith("D:"))

        # Cloud URLs fold the host (and any abfss/oci username) into the path.
        self.assertEqual(
            by_input["s3://host.example:9000/data/file.csv"]["path"],
            "host.example" + "/data/file.csv",
        )
        self.assertTrue(
            by_input[
                "abfss://container@account.dfs.core.windows.net/dir/file.csv"
            ]["path"].startswith("container@")
        )
        self.assertTrue(
            by_input["oci://bucket@namespace/path/to/object"]["path"].startswith(
                "bucket@"
            )
        )

        # Query strings and fragments survive into the parsed path.
        self.assertIn("?", by_input["s3a://bucket/key.csv?versionId=v9"]["path"])
        self.assertIn("#", by_input["gcs://bucket/key.csv#frag"]["path"])
        combo = by_input["s3n://bucket/k.csv?a=1&b=2#sec"]["path"]
        self.assertIn("?", combo)
        self.assertIn("#", combo)

        # A non-cloud scheme with a netloc does NOT fold the host in.
        self.assertEqual(by_input["ftp://example.com/pub/file.csv"]["protocol"], "ftp")
        self.assertEqual(
            by_input["ftp://example.com/pub/file.csv"]["path"], "/pub/file.csv"
        )


if __name__ == "__main__":
    unittest.main()
