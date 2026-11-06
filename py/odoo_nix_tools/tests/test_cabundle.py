"""Finding a CA bundle when OpenSSL can't."""

from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odoo_nix_tools.cabundle import ensure_ca_bundle


def verify_paths(cafile: str | None) -> ssl.DefaultVerifyPaths:
    return ssl.DefaultVerifyPaths(cafile, "/etc/ssl/certs", "SSL_CERT_FILE", "", "SSL_CERT_DIR", "")


class EnsureCaBundle(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bundle = Path(tmp.name) / "bundle.crt"
        self.bundle.touch()
        self.missing = str(Path(tmp.name) / "missing.crt")
        patcher = mock.patch("ssl.get_default_verify_paths", return_value=verify_paths(None))
        self.default_paths = patcher.start()
        self.addCleanup(patcher.stop)

    def test_sets_the_first_bundle_that_exists(self) -> None:
        environ: dict[str, str] = {}
        found = ensure_ca_bundle(environ, (self.missing, str(self.bundle)))
        self.assertEqual(found, str(self.bundle))
        self.assertEqual(environ["SSL_CERT_FILE"], str(self.bundle))

    def test_nix_bundle_comes_first(self) -> None:
        environ = {"NIX_SSL_CERT_FILE": str(self.bundle)}
        ensure_ca_bundle(environ, ("/etc/hostname",))
        self.assertEqual(environ["SSL_CERT_FILE"], str(self.bundle))

    def test_explicit_settings_win(self) -> None:
        for key in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            environ = {key: "/explicit"}
            self.assertIsNone(ensure_ca_bundle(environ, (str(self.bundle),)))
            self.assertEqual(environ, {key: "/explicit"})

    def test_openssl_default_file_wins(self) -> None:
        self.default_paths.return_value = verify_paths("/etc/ssl/cert.pem")
        environ: dict[str, str] = {}
        self.assertIsNone(ensure_ca_bundle(environ, (str(self.bundle),)))
        self.assertEqual(environ, {})

    def test_no_bundle_leaves_the_environment_alone(self) -> None:
        environ: dict[str, str] = {}
        self.assertIsNone(ensure_ca_bundle(environ, (self.missing,)))
        self.assertEqual(environ, {})


if __name__ == "__main__":
    unittest.main()
