"""
Clerk webhook signature verification utility.
"""

import hmac
import hashlib
import os


def verify_clerk_signature(request, webhook_secret):
    """
    Verify Clerk webhook signature.

    Clerk sends signatures in the "svix-id", "svix-timestamp", and "svix-signature"
    headers. The signature is an HMAC-SHA256 of the timestamp + payload.

    Args:
        request: Flask request object
        webhook_secret: Clerk webhook secret from dashboard

    Returns:
        bool: True if signature is valid
    """
    svix_id = request.headers.get("svix-id", "")
    svix_timestamp = request.headers.get("svix-timestamp", "")
    svix_signature = request.headers.get("svix-signature", "")

    if not all([svix_id, svix_timestamp, svix_signature]):
        return False

    # Get raw body
    payload = request.get_data()

    # Create the message to sign: timestamp + payload
    signed_payload = f"{svix_timestamp}{payload.decode('utf-8')}"

    # Calculate expected signature
    secret = webhook_secret.encode("utf-8")
    expected_sig = hmac.new(
        secret,
        signed_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    # Clerk signature format: "v1,<signature>"
    for part in svix_signature.split(","):
        if part.startswith("v1="):
            submitted_sig = part[3:]
            if hmac.compare_digest(expected_sig, submitted_sig):
                return True

    return False