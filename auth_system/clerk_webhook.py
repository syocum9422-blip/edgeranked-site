"""
Clerk webhook signature verification utility.

Clerk delivers webhooks via Svix. Verification scheme:
  - Headers: svix-id, svix-timestamp, svix-signature
  - Signed content:   f"{svix_id}.{svix_timestamp}.{raw_body}"
  - Secret format:    "whsec_<base64>"  -- strip prefix, base64-decode -> raw key
  - Header format:    space-separated list of "v1,<base64-hmac>"
  - Digest:           HMAC-SHA256, base64-encoded raw bytes (NOT hex)
"""

import base64
import hashlib
import hmac
import logging

LOGGER = logging.getLogger(__name__)


def verify_clerk_signature(request, webhook_secret):
    """
    Verify a Clerk/Svix webhook signature.

    Returns True only if a v1 signature in the svix-signature header matches
    the HMAC-SHA256 of the canonical signed content. Logs the failure reason
    (without secrets or payload bytes) for any rejection.
    """
    svix_id = request.headers.get("svix-id", "")
    svix_timestamp = request.headers.get("svix-timestamp", "")
    svix_signature = request.headers.get("svix-signature", "")

    if not (svix_id and svix_timestamp and svix_signature):
        LOGGER.warning(
            "Clerk webhook rejected: missing svix headers (have id=%s ts=%s sig=%s)",
            bool(svix_id), bool(svix_timestamp), bool(svix_signature),
        )
        return False

    if not webhook_secret:
        LOGGER.warning("Clerk webhook rejected: empty webhook secret")
        return False

    secret_value = webhook_secret
    if secret_value.startswith("whsec_"):
        secret_value = secret_value[len("whsec_"):]
    try:
        secret_bytes = base64.b64decode(secret_value)
    except (ValueError, TypeError) as exc:
        LOGGER.error(
            "Clerk webhook rejected: secret is not valid base64 (%s)",
            type(exc).__name__,
        )
        return False

    payload = request.get_data()
    signed_content = f"{svix_id}.{svix_timestamp}.".encode("utf-8") + payload

    expected_sig = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode("utf-8")

    for part in svix_signature.split(" "):
        if not part:
            continue
        version, _, candidate = part.partition(",")
        if version != "v1" or not candidate:
            continue
        if hmac.compare_digest(expected_sig, candidate):
            return True

    LOGGER.warning("Clerk webhook rejected: no matching v1 signature in header")
    return False
