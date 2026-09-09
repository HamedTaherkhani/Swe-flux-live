import random
import unittest
from unittest import mock

import scrapy.utils.ssl as ssl_utils


class _FFI:
    NULL = object()

    def new(self, declaration):
        if declaration != "EVP_PKEY **":
            raise AssertionError(declaration)
        return [self.NULL]

    def gc(self, value, destructor):
        if value is self.NULL:
            raise AssertionError("cannot own a null pointer")
        return value

    def string(self, value):
        if not isinstance(value, bytes):
            raise TypeError(type(value))
        return value


class _BaseLib:
    EVP_PKEY_RSA = 101
    EVP_PKEY_DH = 202
    EVP_PKEY_EC = 303

    @staticmethod
    def EVP_PKEY_free(value):
        return None

    @staticmethod
    def EC_KEY_free(value):
        return None

    @staticmethod
    def EVP_PKEY_id(key):
        return key["kind"]

    @staticmethod
    def EVP_PKEY_bits(key):
        return key["bits"]

    @staticmethod
    def EVP_PKEY_get1_EC_KEY(key):
        return {"curve": key["curve"], "fallback": key["fallback"]}

    @staticmethod
    def EC_KEY_get0_group(ec_key):
        return ec_key

    @staticmethod
    def EC_GROUP_get_curve_name(group):
        return group

    def EC_curve_nid2nist(self, nid):
        if nid["fallback"]:
            return self._ffi.NULL
        return f"nist-{nid['curve']}".encode()

    @staticmethod
    def OBJ_nid2sn(value):
        if isinstance(value, dict):
            value = value["curve"]
        return f"short-{value}".encode()


class _LibWithoutTempKey(_BaseLib):
    def __init__(self, ffi):
        self._ffi = ffi


class _LibWithTempKey(_BaseLib):
    def __init__(self, ffi, descriptor):
        self._ffi = ffi
        self._descriptor = descriptor

    def SSL_get_server_tmp_key(self, ssl_object, destination):
        if self._descriptor["mode"] == "reject":
            return 0
        if self._descriptor["mode"] == "null":
            destination[0] = self._ffi.NULL
        else:
            destination[0] = self._descriptor
        return 1


class _Connection:
    def __init__(self, descriptor):
        self._ssl = {"token": descriptor["token"]}
        self._descriptor = descriptor
        self.protocol_reads = 0
        self.cipher_reads = 0

    def get_protocol_version_name(self):
        self.protocol_reads += 1
        return f"TLSv1.{self._descriptor['token'] % 4}"

    def get_cipher_name(self):
        self.cipher_reads += 1
        return f"CIPHER-{self._descriptor['token'] % 23}"

    def get_peer_certificate(self, **kwargs):
        return None


def _descriptor(mode, seed, ordinal):
    kind_by_mode = {
        "rsa": _BaseLib.EVP_PKEY_RSA,
        "dh": _BaseLib.EVP_PKEY_DH,
        "ec": _BaseLib.EVP_PKEY_EC,
        "ec_fallback": _BaseLib.EVP_PKEY_EC,
    }
    token = (seed * 977 + ordinal * 131) % 10007
    return {
        "mode": mode,
        "kind": kind_by_mode.get(mode, 700 + token % 89),
        "bits": 256 + 128 * (1 + token % 31),
        "curve": 400 + token % 97,
        "fallback": mode == "ec_fallback",
        "token": token,
    }


class TestTempKeyInfoDataFlow(unittest.TestCase):
    def _exercise(self, seed, total, stride):
        rng = random.Random(seed)
        branch_families = [
            "unsupported",
            "reject",
            "null",
            "rsa",
            "dh",
            "ec",
            "ec_fallback",
            "other",
        ]
        offset = (seed * stride) % len(branch_families)
        modes = [
            branch_families[
                (offset + ordinal * stride + rng.randrange(len(branch_families)))
                % len(branch_families)
            ]
            for ordinal in range(total)
        ]
        modes[: len(branch_families)] = branch_families[offset:] + branch_families[:offset]

        completed = 0
        for ordinal, mode in enumerate(modes):
            descriptor = _descriptor(mode, seed, ordinal)
            ffi = _FFI()
            if mode == "unsupported":
                lib = _LibWithoutTempKey(ffi)
            else:
                lib = _LibWithTempKey(ffi, descriptor)
            facade = type("OpenSSLFacade", (), {"ffi": ffi, "lib": lib})()
            connection = _Connection(descriptor)
            with (
                mock.patch.object(ssl_utils, "pyOpenSSLutil", facade),
                mock.patch.object(ssl_utils, "PYOPENSSL_X509_DEPRECATED", True),
            ):
                ssl_utils._log_ssl_conn_debug_info(
                    f"peer-{(descriptor['token'] * 17) % 997}.invalid", connection
                )
            self.assertEqual(connection.protocol_reads, 1)
            self.assertEqual(connection.cipher_reads, 1)
            completed += connection.protocol_reads

        self.assertEqual(completed, len(modes))
        self.assertGreater(len(set(modes)), 4)

    def test_01_rotating_prime(self):
        self._exercise(107, 19, 3)

    def test_02_even_stride(self):
        self._exercise(211, 22, 2)

    def test_03_dense_rotation(self):
        self._exercise(313, 25, 5)

    def test_04_reverse_cycle(self):
        self._exercise(419, 21, 7)

    def test_05_short_wide_mix(self):
        self._exercise(523, 24, 1)

    def test_06_offset_mix(self):
        self._exercise(631, 27, 3)

    def test_07_long_even_mix(self):
        self._exercise(739, 30, 2)

    def test_08_curve_heavy_seed(self):
        self._exercise(853, 23, 5)

    def test_09_fallback_heavy_seed(self):
        self._exercise(967, 26, 7)

    def test_10_large_cycle(self):
        self._exercise(1087, 29, 1)

    def test_11_alternate_cycle(self):
        self._exercise(1201, 28, 3)

    def test_12_final_rotation(self):
        self._exercise(1307, 31, 5)
