import tempfile
import unittest
from pathlib import Path

from autokdewallet.salt import SALT_SIZE, load_binary_salt


class LoadBinarySaltTests(unittest.TestCase):
    def test_reads_valid_salt(self):
        salt = bytes(range(SALT_SIZE))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kdewallet.salt"
            path.write_bytes(salt)
            self.assertEqual(load_binary_salt(path), salt)

    def test_missing_salt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_binary_salt(Path(tmp) / "missing.salt")

    def test_wrong_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kdewallet.salt"
            path.write_bytes(b"too short")
            with self.assertRaises(ValueError):
                load_binary_salt(path)


if __name__ == "__main__":
    unittest.main()
