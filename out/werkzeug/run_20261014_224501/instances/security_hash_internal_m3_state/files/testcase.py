import random
import unittest

from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash


def _rng(tag):
    return random.Random(f"security-m3-{tag}")


class TestPasswordHashState(unittest.TestCase):
    def test_default_scrypt_roundtrip(self):
        stored = generate_password_hash("correct horse")
        self.assertTrue(check_password_hash(stored, "correct horse"))
        self.assertFalse(check_password_hash(stored, "wrong horse"))

    def test_scrypt_params_from_rng(self):
        rng = _rng("scrypt")
        for i in range(4):
            n = 2 ** rng.randint(7, 11)
            r = rng.randint(1, 6)
            p = rng.choice([1, 2, 3])
            stored = generate_password_hash(f"pw{i}", method=f"scrypt:{n}:{r}:{p}")
            self.assertEqual(stored.count("$"), 2)
            self.assertTrue(check_password_hash(stored, f"pw{i}"))

    def test_scrypt_odd_integer_spellings(self):
        rng = _rng("spell")
        exp = rng.randint(8, 10)
        width = rng.randint(3, 5)
        n_text = str(2**exp).zfill(width)
        r_text = "+" + str(rng.randint(2, 4))
        p_text = "1_" + str(rng.randint(0, 1))
        stored = generate_password_hash("spelled", method=":".join(["scrypt", n_text, r_text, p_text]))
        self.assertTrue(stored.startswith("scrypt:"))
        self.assertTrue(check_password_hash(stored, "spelled"))

    def test_handbuilt_scrypt_hash_mismatch(self):
        rng = _rng("hand")
        n = 1 << (rng.randint(6, 8) + 1)
        pwhash = f"scrypt:{n}:{n // 4}:{1 + n % 3}$saltysalt$deadbeef"
        self.assertFalse(check_password_hash(pwhash, "anything"))

    def test_pbkdf2_explicit_iterations(self):
        rng = _rng("pbkdf2")
        for name in ["sha1", "sha256", "md5"]:
            iters = rng.randint(50, 900) * rng.randint(1, 3)
            stored = generate_password_hash(name * 2, method=f"pbkdf2:{name}:{iters}")
            self.assertTrue(check_password_hash(stored, name * 2))

    def test_pbkdf2_default_iterations_named_hash(self):
        stored = generate_password_hash("long secret", method="pbkdf2:sha512", salt_length=4)
        self.assertEqual(len(stored.split("$")[1]) > 0, True)
        self.assertTrue(check_password_hash(stored, "long secret"))

    def test_pbkdf2_underscored_iterations(self):
        rng = _rng("under")
        digits = [str(rng.randint(1, 9)) for _ in range(3)]
        method = "pbkdf2:sha224:" + "_".join(digits)
        stored = generate_password_hash("u", method=method)
        self.assertFalse(check_password_hash(stored, "v"))

    def test_invalid_method_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid"):
            generate_password_hash("x", method="bcrypt:12")

    def test_scrypt_wrong_arity(self):
        with self.assertRaisesRegex(ValueError, "takes"):
            check_password_hash("scrypt:16:8$abc$def", "x")
        with self.assertRaisesRegex(ValueError, "takes"):
            generate_password_hash("x", method="scrypt:16:eight:1")

    def test_pbkdf2_wrong_arity_and_bad_digest(self):
        with self.assertRaisesRegex(ValueError, "takes"):
            generate_password_hash("x", method="pbkdf2:sha256:10:extra")
        with self.assertRaises(ValueError):
            check_password_hash("pbkdf2:sha999:10$abc$def", "x")

    def test_malformed_hash_short_circuits(self):
        self.assertFalse(check_password_hash("no-dollar-signs-here", "x"))
        self.assertFalse(check_password_hash("one$dollar", "x"))
        rng = _rng("mal")
        iters = rng.randint(10, 99)
        self.assertFalse(check_password_hash(f"pbkdf2:sha384:{iters}$s$h$extra", "x"))

    def test_scrypt_parallelism_sweep(self):
        base = _rng("sweep").randint(2, 4)
        for p in range(1, 4):
            r = base + p
            stored = generate_password_hash("sweep", method=f"scrypt:{2 ** (p + 6)}:{r}:{p}", salt_length=8)
            self.assertTrue(check_password_hash(stored, "sweep"))
