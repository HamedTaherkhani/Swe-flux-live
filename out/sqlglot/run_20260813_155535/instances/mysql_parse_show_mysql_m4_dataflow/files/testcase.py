import random
import unittest

from sqlglot import Dialect, exp
from sqlglot.parsers.mysql import MySQLParser


class TestMySQLShowDataFlow(unittest.TestCase):
    def _invoke(self, this, suffix, *, target=False, full=None, global_=None):
        dialect = Dialect.get_or_raise("mysql")
        parser = MySQLParser(dialect=dialect)
        tokens = dialect.tokenize(suffix)
        parser._tokens = tokens
        parser._tokens_size = len(tokens)
        parser._index = -1
        parser._advance()

        result = parser._parse_show_mysql(
            this, target=target, full=full, global_=global_
        )

        self.assertIsInstance(result, exp.Show)
        self.assertEqual(result.this, this)
        self.assertGreaterEqual(parser._index, 0)
        return result

    def _run_batch(self, seed, families, rounds):
        rng = random.Random(seed * seed + rounds * 17)
        checksum = 0
        for index in range(rounds):
            family = families[(index * 7 + rng.randrange(len(families))) % len(families)]
            value = seed * 31 + index * 13 + rng.randrange(97)
            name = f"n_{value:x}_{(value * value + seed) % 101:x}"

            if family == "basic":
                this = ("STATUS", "TABLES", "VARIABLES")[value % 3]
                prefix = "JSON " if value % 2 else ""
                result = self._invoke(
                    this,
                    f"{prefix}LIMIT {value % 9 + 1}",
                    full=bool(value % 2),
                    global_=bool(value % 3),
                )
            elif family == "target_from":
                dotted = f".leaf_{(value * 5) % 29}" if value % 2 else ""
                result = self._invoke(
                    "COLUMNS",
                    f"FROM {name}{dotted} LIMIT {value % 5 + 1}, {value % 11 + 2}",
                    target="FROM",
                    full=bool(value % 2),
                )
            elif family == "target_true":
                dotted = f".part_{(value * 3) % 23}" if value % 3 else ""
                result = self._invoke(
                    "CREATE TABLE",
                    f"{name}{dotted} LIMIT {value % 7 + 1}",
                    target=True,
                )
            elif family == "log":
                result = self._invoke(
                    "BINARY LOGS",
                    f"IN 'log_{name}' LIMIT {value % 4 + 1}, {value % 13 + 2}",
                )
            elif family == "database":
                result = self._invoke(
                    "TABLE STATUS",
                    f"IN {name} LIKE 'p_{value % 17}_%' LIMIT {value % 8 + 1}",
                )
            elif family == "binlog":
                result = self._invoke(
                    "BINLOG EVENTS",
                    f"FROM {value % 401 + 1} LIMIT {value % 6 + 1}, {value % 19 + 2}",
                )
            elif family == "relay":
                result = self._invoke(
                    "RELAYLOG EVENTS",
                    f"FROM {value % 503 + 1} FOR CHANNEL ch_{name} LIMIT {value % 12 + 1}",
                )
            elif family == "filters":
                result = self._invoke(
                    "EVENTS",
                    (
                        f"FROM db_{name} LIKE 'event_{value % 31}_%' "
                        f"WHERE metric > {value % 37} LIMIT {value % 5 + 1}, {value % 17 + 2}"
                    ),
                )
            elif family == "profile":
                profile_types = ("CPU", "BLOCK IO", "CONTEXT SWITCHES", "PAGE FAULTS")
                first = profile_types[value % len(profile_types)]
                second = profile_types[(value + seed) % len(profile_types)]
                result = self._invoke(
                    "PROFILE",
                    (
                        f"{first}, {second} FOR QUERY {value % 211 + 1} "
                        f"OFFSET {value % 23 + 1} LIMIT {value % 41 + 2}"
                    ),
                )
            elif family == "mutex":
                result = self._invoke(
                    "STATUS",
                    (
                        f"LIMIT {value % 13 + 1} MUTEX FOR TABLE tab_{name} "
                        f"FOR GROUP 'grp_{value % 19}' FOR USER 'usr_{value % 23}' "
                        f"FOR ROLE 'role_{value % 29}' INTO OUTFILE 'out_{name}'"
                    ),
                )
            elif family == "status":
                result = self._invoke(
                    "STATUS",
                    (
                        f"LIMIT {value % 7 + 1}, {value % 17 + 2} STATUS "
                        f"FOR USER 'user_{name}' FOR ROLE 'reader_{value % 31}'"
                    ),
                )
            else:
                result = self._invoke(
                    "WARNINGS",
                    (
                        f"LIMIT {value % 11 + 1} FOR GROUP 'g_{name}' "
                        f"INTO OUTFILE 'report_{value % 43}'"
                    ),
                )

            checksum ^= len(result.args) * (index + 1) + len(result.this)

        self.assertIsInstance(checksum, int)
        self.assertGreater(rounds, len(families))

    def test_generated_basics_and_targets(self):
        self._run_batch(5, ("basic", "target_from", "target_true"), 19)

    def test_generated_logs_and_databases(self):
        self._run_batch(7, ("log", "database", "filters"), 21)

    def test_generated_binary_event_positions(self):
        self._run_batch(11, ("binlog", "relay", "log"), 23)

    def test_generated_profile_variants(self):
        self._run_batch(13, ("profile", "basic", "filters"), 20)

    def test_generated_mutex_extensions(self):
        self._run_batch(17, ("mutex", "status", "outfile"), 22)

    def test_generated_dotted_targets(self):
        self._run_batch(19, ("target_from", "target_true", "database"), 18)

    def test_generated_filter_combinations(self):
        self._run_batch(23, ("filters", "database", "basic", "status"), 24)

    def test_generated_channels_and_limits(self):
        self._run_batch(29, ("relay", "binlog", "mutex"), 25)

    def test_generated_output_destinations(self):
        self._run_batch(31, ("outfile", "mutex", "log"), 17)

    def test_generated_profile_target_mix(self):
        self._run_batch(37, ("profile", "target_from", "target_true", "basic"), 26)

    def test_generated_status_scope_mix(self):
        self._run_batch(41, ("status", "basic", "database", "mutex"), 27)

    def test_generated_all_branch_families(self):
        self._run_batch(
            43,
            (
                "basic",
                "target_from",
                "target_true",
                "log",
                "database",
                "binlog",
                "relay",
                "filters",
                "profile",
                "mutex",
                "status",
                "outfile",
            ),
            29,
        )
