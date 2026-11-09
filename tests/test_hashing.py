import hashlib
import unittest

from autokdewallet.hashing import HASH_ALGO, ITERATIONS, KEY_SIZE, derive_kwallet_hash


class DeriveKWalletHashTests(unittest.TestCase):
    def test_matches_kwallet_parameters(self):
        expected = hashlib.pbkdf2_hmac(
            "sha512", b"password", b"salt", 50_000, 56
        )
        self.assertEqual(derive_kwallet_hash(b"password", b"salt"), expected)

    def test_constants(self):
        self.assertEqual(HASH_ALGO, "sha512")
        self.assertEqual(ITERATIONS, 50_000)
        self.assertEqual(KEY_SIZE, 56)

    def test_output_length(self):
        key = derive_kwallet_hash(b"password", b"a" * 56)
        self.assertEqual(len(key), KEY_SIZE)

    def test_known_vector(self):
        # Regression guard for the KWallet-compatible derivation.
        key = derive_kwallet_hash(b"correct horse", b"kdewallet-salt").hex()
        self.assertEqual(len(key), KEY_SIZE * 2)
        self.assertEqual(
            key,
            hashlib.pbkdf2_hmac(
                "sha512", b"correct horse", b"kdewallet-salt", 50_000, 56
            ).hex(),
        )


if __name__ == "__main__":
    unittest.main()
