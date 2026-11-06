"""Find a CA bundle for an interpreter that can't find one by itself.

The workflows install the tools with ``uv tool install``, on a standalone Python whose
OpenSSL looks in ``/etc/ssl/cert.pem`` and for hashed files in ``/etc/ssl/certs``. NixOS has
neither, so on a self-hosted runner every HTTPS fetch of an org profile fails with
CERTIFICATE_VERIFY_FAILED, though the bundle itself is right there.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import MutableMapping
from pathlib import Path

CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",  # NixOS, Debian, Ubuntu
    "/etc/ssl/certs/ca-bundle.crt",  # NixOS, older Fedora
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL
)


def ensure_ca_bundle(
    environ: MutableMapping[str, str] = os.environ,
    candidates: tuple[str, ...] = CANDIDATES,
) -> str | None:
    """Point ``SSL_CERT_FILE`` at a bundle if OpenSSL has no file of its own.

    An explicit ``SSL_CERT_FILE`` or ``SSL_CERT_DIR`` wins. Returns the path it set, if any.
    """
    if environ.get("SSL_CERT_FILE") or environ.get("SSL_CERT_DIR"):
        return None
    if ssl.get_default_verify_paths().cafile:
        return None
    for candidate in (environ.get("NIX_SSL_CERT_FILE", ""), *candidates):
        if candidate and Path(candidate).is_file():
            environ["SSL_CERT_FILE"] = candidate
            return candidate
    return None
