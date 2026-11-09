import os
import unittest
from unittest import mock

from autokdewallet import unlock


class EnvironmentPayloadTests(unittest.TestCase):
    def test_includes_socket_variable(self):
        with mock.patch.dict(os.environ, {"AUTOKDEWALLET_TEST": "1"}, clear=True):
            payload = unlock.environment_payload("/run/user/1000/kwallet5.socket")
        lines = payload.decode().splitlines()
        self.assertIn("AUTOKDEWALLET_TEST=1", lines)
        self.assertIn(
            f"{unlock.ENV_VAR}=/run/user/1000/kwallet5.socket", lines
        )

    def test_skips_values_containing_newlines(self):
        with mock.patch.dict(os.environ, {"BAD": "a\nb"}, clear=True):
            payload = unlock.environment_payload("/tmp/kwallet5.socket")
        self.assertNotIn(b"BAD=", payload)

    def test_skips_overlong_lines(self):
        with mock.patch.dict(os.environ, {"LONG": "x" * unlock.ENV_LINE_MAX}, clear=True):
            payload = unlock.environment_payload("/tmp/kwallet5.socket")
        self.assertNotIn(b"LONG=", payload)

    def test_extra_environment_wins(self):
        with mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True):
            payload = unlock.environment_payload(
                "/tmp/kwallet5.socket", {"DISPLAY": ":1"}
            )
        self.assertIn("DISPLAY=:1", payload.decode())
        self.assertNotIn("DISPLAY=:0", payload.decode())


if __name__ == "__main__":
    unittest.main()
