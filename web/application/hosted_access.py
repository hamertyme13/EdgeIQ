"""Single-operator access gate for a private hosted beta."""

from __future__ import annotations

import base64
import binascii
import hmac
import os


def hosted_access_required() -> bool:
    mode = os.getenv("EDGEIQ_DEPLOYMENT_MODE", "").strip().lower()
    return mode == "hosted" or bool(os.getenv("RAILWAY_ENVIRONMENT"))


def hosted_access_status(authorization: str | None) -> str:
    """Return allowed, credentials_required, or unavailable without logging secrets."""
    if not hosted_access_required():
        return "allowed"
    password = os.getenv("EDGEIQ_HOSTED_ACCESS_PASSWORD", "")
    if not password:
        return "unavailable"
    try:
        scheme, encoded = (authorization or "").split(" ", 1)
        if scheme.lower() != "basic":
            return "credentials_required"
        username, supplied_password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return "credentials_required"
    expected_user = os.getenv("EDGEIQ_HOSTED_ACCESS_USER", "edgeiq")
    if hmac.compare_digest(username, expected_user) and hmac.compare_digest(supplied_password, password):
        return "allowed"
    return "credentials_required"
