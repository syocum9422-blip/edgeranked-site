"""
Stripe integration for subscription management.
Handles checkout, webhooks, and subscription status checks.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from urllib.parse import quote
from urllib.request import urlopen

import stripe
from flask import current_app, jsonify, request

from auth_system.models import (
    db,
    User,
    create_or_update_user,
    log_subscription_event,
    update_subscription,
)

LOGGER = logging.getLogger(__name__)

# Stripe configuration
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")  # $19.99/month price ID
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")

# Subscription tier configuration
SUBSCRIPTION_PRICE_MONTHLY = 19.99  # USD
SUBSCRIPTION_PRICE_ANNUAL = 199.99  # USD (save ~17%)

stripe.api_key = STRIPE_SECRET_KEY


def _so_get(obj, key, default=None):
    """Dict.get-style lookup that also works on stripe-python>=8 StripeObject.

    StripeObject no longer inherits from dict, so `obj.get(key, default)` raises
    AttributeError. Bracket access works but raises KeyError on missing keys;
    this wrapper restores the soft-fail dict.get semantics for both shapes.
    """
    try:
        return obj[key]
    except (KeyError, TypeError, AttributeError):
        return default


def get_stripe_publishable_key():
    """Return Stripe publishable key for frontend."""
    return STRIPE_PUBLISHABLE_KEY


def check_subscription_status(user_id):
    """
    Check if user has active subscription.
    Called by auth decorators to verify subscription access.

    Args:
        user_id: Clerk user ID

    Returns:
        bool: True if user has active subscription
    """
    user = User.query.filter_by(clerk_user_id=user_id).first()
    if not user:
        return False

    # "trialing" grants the same premium access as "active" (3-day free trial).
    if user.subscription_status not in ("active", "trialing"):
        return False

    if user.subscription_current_period_end:
        if user.subscription_current_period_end < datetime.now(user.subscription_current_period_end.tzinfo):
            return False

    return True


def create_checkout_session(user_id, price_id=None, success_url="/mlb?subscribed=true",
                            cancel_url="/upgrade?canceled=true"):
    """
    Create Stripe checkout session for subscription.

    Args:
        user_id: Clerk user ID
        price_id: Stripe price ID (uses STRIPE_PRICE_ID if not provided)
        success_url: URL to redirect after successful checkout
        cancel_url: URL to redirect if checkout is canceled

    Returns:
        dict: Session ID and URL for Stripe checkout
    """
    if not price_id:
        price_id = STRIPE_PRICE_ID

    if not price_id:
        raise ValueError("No Stripe price ID configured")

    user = User.query.filter_by(clerk_user_id=user_id).first()
    if not user:
        raise ValueError(f"User not found: {user_id}")

    LOGGER.info(
        "checkout: starting clerk_user_id=%s has_existing_customer=%s",
        user_id, bool(user.stripe_customer_id),
    )

    # Get or create Stripe customer
    customer_id = user.stripe_customer_id
    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"clerk_user_id": user_id}
            )
            customer_id = customer.id
            user.stripe_customer_id = customer_id
            db.session.commit()
            LOGGER.info(
                "checkout: created stripe customer clerk_user_id=%s customer_id=%s",
                user_id, customer_id,
            )
        except stripe.error.StripeError as e:
            LOGGER.error(f"Failed to create Stripe customer: {e}")
            raise
    else:
        LOGGER.info(
            "checkout: reusing stripe customer clerk_user_id=%s customer_id=%s",
            user_id, customer_id,
        )

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="subscription",
            subscription_data={
                "metadata": {"clerk_user_id": user_id},
                "trial_period_days": 3,
            },
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
        )
        LOGGER.info(
            "checkout: session created clerk_user_id=%s session_id=%s customer_id=%s price_id=%s",
            user_id, session.id, customer_id, price_id,
        )
        return {
            "session_id": session.id,
            "url": session.url,
        }
    except stripe.error.StripeError as e:
        LOGGER.error(f"Failed to create checkout session: {e}")
        raise


def create_customer_portal_session(user_id, return_url="/upgrade"):
    """
    Create Stripe customer portal session for managing subscription.

    Args:
        user_id: Clerk user ID
        return_url: URL to redirect after exiting portal

    Returns:
        dict: Session URL for Stripe customer portal
    """
    user = User.query.filter_by(clerk_user_id=user_id).first()
    if not user or not user.stripe_customer_id:
        raise ValueError("No Stripe customer found for user")

    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        return {"url": session.url}
    except stripe.error.StripeError as e:
        LOGGER.error(f"Failed to create portal session: {e}")
        raise


def register_stripe_routes(flask_app):
    """
    Register Stripe-related routes on the Flask app.
    Call this from create_app().

    Routes registered:
    - /api/stripe/config - Get Stripe publishable key
    - /api/stripe/create-checkout - Create checkout session
    - /api/stripe/create-portal - Create customer portal session
    - /api/stripe/subscription - Get current subscription status
    - /webhooks/stripe - Stripe webhooks
    """

    @flask_app.get("/api/stripe/config")
    def stripe_config():
        """Return Stripe publishable key for frontend."""
        return jsonify({
            "publishable_key": STRIPE_PUBLISHABLE_KEY,
        })

    @flask_app.post("/api/stripe/create-checkout")
    def create_checkout():
        """Create Stripe checkout session for subscription."""
        from auth_system.auth import get_clerk_user_id

        user_id = get_clerk_user_id()
        if not user_id:
            return jsonify({"error": "Authentication required"}), 401

        price_id = None
        next_path = None
        if request.is_json:
            data = request.get_json(silent=True) or {}
            price_id = data.get("price_id")
            next_path = data.get("next")

        # Validate optional `next` to a safe relative same-origin path so an
        # attacker cannot smuggle an external URL through Stripe's success_url.
        safe_next = None
        if isinstance(next_path, str):
            candidate = next_path.strip()
            if (candidate.startswith("/")
                    and not candidate.startswith("//")
                    and "\n" not in candidate
                    and "\r" not in candidate):
                safe_next = candidate

        # Stripe requires absolute https URLs. Build them from SITE_BASE_URL
        # (env-driven) with a request.url_root fallback so the route never
        # forwards Stripe a relative path (which raises "Not a valid URL").
        base = SITE_BASE_URL or request.url_root.rstrip("/")
        success_url = f"{base}/account?subscribed=true"
        if safe_next:
            success_url += f"&next={quote(safe_next)}"
        cancel_url = f"{base}/pricing?canceled=true"
        LOGGER.info(
            "checkout: site_base=%s success_url=%s cancel_url=%s",
            base, success_url, cancel_url,
        )

        try:
            result = create_checkout_session(
                user_id, price_id,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except stripe.error.StripeError as e:
            LOGGER.error(f"Stripe checkout error: {e}")
            return jsonify({"error": "Failed to create checkout session"}), 500

    @flask_app.post("/api/stripe/create-portal")
    def create_portal():
        """Create Stripe customer portal session."""
        from auth_system.auth import get_clerk_user_id

        user_id = get_clerk_user_id()
        if not user_id:
            return jsonify({"error": "Authentication required"}), 401

        try:
            result = create_customer_portal_session(user_id)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except stripe.error.StripeError as e:
            LOGGER.error(f"Stripe portal error: {e}")
            return jsonify({"error": "Failed to create portal session"}), 500

    @flask_app.get("/api/stripe/subscription")
    def get_subscription():
        """Get current user's subscription status."""
        from auth_system.auth import get_clerk_user_id

        user_id = get_clerk_user_id()
        if not user_id:
            return jsonify({"error": "Authentication required"}), 401

        user = User.query.filter_by(clerk_user_id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "subscribed": user.is_subscribed,
            "status": user.subscription_status,
            "plan": user.subscription_plan,
            "current_period_end": (
                user.subscription_current_period_end.isoformat()
                if user.subscription_current_period_end else None
            ),
            "stripe_customer_id": user.stripe_customer_id,
        })

    @flask_app.post("/webhooks/stripe")
    def stripe_webhook():
        """
        Handle Stripe webhooks for subscription lifecycle.
        Events handled:
        - checkout.session.completed
        - customer.subscription.created
        - customer.subscription.updated
        - customer.subscription.deleted
        - invoice.payment_succeeded
        - invoice.payment_failed
        """
        payload = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")
        event = None

        # Verify webhook signature. Fail closed if the signing secret is absent.
        if not STRIPE_WEBHOOK_SECRET:
            LOGGER.error("Stripe webhook signing secret is not configured")
            return jsonify({"error": "Webhook signing secret not configured"}), 503
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            LOGGER.error("Invalid webhook payload")
            return jsonify({"error": "Invalid payload"}), 400
        except stripe.error.SignatureVerificationError:
            LOGGER.error("Invalid webhook signature")
            return jsonify({"error": "Invalid signature"}), 400

        # stripe-python >=8 returns Event objects whose `.get` is not the dict
        # method (the class no longer inherits from dict). Use bracket access.
        event_type = event["type"]
        data = event["data"]["object"]

        LOGGER.info(f"Stripe webhook: {event_type}")

        try:
            if event_type == "checkout.session.completed":
                _handle_checkout_completed(data)
            elif event_type == "customer.subscription.created":
                _handle_subscription_created(data)
            elif event_type == "customer.subscription.updated":
                _handle_subscription_updated(data)
            elif event_type == "customer.subscription.deleted":
                _handle_subscription_deleted(data)
            elif event_type == "invoice.payment_succeeded":
                _handle_payment_succeeded(data)
            elif event_type == "invoice.payment_failed":
                _handle_payment_failed(data)
        except Exception as e:
            LOGGER.error(f"Webhook handler error for {event_type}: {e}")
            return jsonify({"error": "Handler error"}), 500

        return jsonify({"received": True})


def _handle_checkout_completed(data):
    """Handle successful checkout session completion."""
    customer_id = _so_get(data, "customer")
    subscription_id = _so_get(data, "subscription")
    metadata = _so_get(data, "metadata") or {}
    clerk_user_id = _so_get(metadata, "clerk_user_id")

    LOGGER.info(
        "stripe.checkout.completed: customer_id=%s subscription_id=%s has_metadata_clerk_id=%s",
        customer_id, subscription_id, bool(clerk_user_id),
    )

    if not customer_id:
        LOGGER.warning("Checkout completed without customer ID")
        return

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user and clerk_user_id:
        user = User.query.filter_by(clerk_user_id=clerk_user_id).first()
        LOGGER.info(
            "stripe.checkout.completed: user lookup by metadata clerk_user_id=%s found=%s",
            clerk_user_id, bool(user),
        )
    else:
        LOGGER.info(
            "stripe.checkout.completed: user lookup by customer_id=%s found=%s",
            customer_id, bool(user),
        )

    if user:
        if subscription_id and not user.stripe_subscription_id:
            user.stripe_subscription_id = subscription_id
        user.subscription_status = "active"
        db.session.commit()
        LOGGER.info(
            "stripe.checkout.completed: committed clerk_user_id=%s status=active subscription_id=%s",
            user.clerk_user_id, user.stripe_subscription_id,
        )

        log_subscription_event(
            user_id=user.id,
            event_type="checkout_completed",
            stripe_event_id=_so_get(data, "id"),
            stripe_customer_id=customer_id,
            new_status="active",
        )
    else:
        LOGGER.warning(
            "stripe.checkout.completed: no matching user customer_id=%s metadata_clerk_id=%s",
            customer_id, clerk_user_id,
        )


def _handle_subscription_created(data):
    """Handle new subscription creation."""
    customer_id = _so_get(data, "customer")
    subscription_id = _so_get(data, "id")
    status = _so_get(data, "status")
    current_period_end = _so_get(data, "current_period_end")

    LOGGER.info(
        "stripe.subscription.created: customer_id=%s subscription_id=%s status=%s",
        customer_id, subscription_id, status,
    )

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        LOGGER.warning(f"Subscription created for unknown customer: {customer_id}")
        return
    LOGGER.info(
        "stripe.subscription.created: matched user clerk_user_id=%s -> writing status=%s",
        user.clerk_user_id, status,
    )

    period_end = None
    if current_period_end:
        period_end = datetime.fromtimestamp(current_period_end)

    update_subscription(
        user_id=user.id,
        stripe_subscription_id=subscription_id,
        status=status,
        period_end=period_end,
    )

    log_subscription_event(
        user_id=user.id,
        event_type="created",
        stripe_event_id=_so_get(data, "id"),
        stripe_subscription_id=subscription_id,
        stripe_customer_id=customer_id,
        new_status=status,
    )


def _handle_subscription_updated(data):
    """Handle subscription updates (plan changes, status changes)."""
    customer_id = _so_get(data, "customer")
    subscription_id = _so_get(data, "id")
    status = _so_get(data, "status")
    old_status = None
    current_period_end = _so_get(data, "current_period_end")

    LOGGER.info(
        "stripe.subscription.updated: customer_id=%s subscription_id=%s status=%s",
        customer_id, subscription_id, status,
    )

    # Get previous status from database
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if user:
        old_status = user.subscription_status
        LOGGER.info(
            "stripe.subscription.updated: matched user clerk_user_id=%s old_status=%s -> %s",
            user.clerk_user_id, old_status, status,
        )
    else:
        LOGGER.warning(
            "stripe.subscription.updated: no user for customer_id=%s",
            customer_id,
        )

    period_end = None
    if current_period_end:
        period_end = datetime.fromtimestamp(current_period_end)

    if user:
        update_subscription(
            user_id=user.id,
            status=status,
            period_end=period_end,
        )

        log_subscription_event(
            user_id=user.id,
            event_type="updated",
            stripe_event_id=_so_get(data, "id"),
            stripe_subscription_id=subscription_id,
            stripe_customer_id=customer_id,
            old_status=old_status,
            new_status=status,
        )


def _handle_subscription_deleted(data):
    """Handle subscription cancellation/deletion."""
    customer_id = _so_get(data, "customer")
    subscription_id = _so_get(data, "id")

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        LOGGER.warning(f"Subscription deleted for unknown customer: {customer_id}")
        return

    old_status = user.subscription_status
    update_subscription(
        user_id=user.id,
        status="canceled",
    )

    log_subscription_event(
        user_id=user.id,
        event_type="deleted",
        stripe_event_id=_so_get(data, "id"),
        stripe_subscription_id=subscription_id,
        stripe_customer_id=customer_id,
        old_status=old_status,
        new_status="canceled",
    )


def _handle_payment_succeeded(data):
    """Handle successful payment (subscription renewal)."""
    customer_id = _so_get(data, "customer")
    subscription_id = _so_get(data, "subscription")

    LOGGER.info(
        "stripe.payment.succeeded: customer_id=%s subscription_id=%s",
        customer_id, subscription_id,
    )

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        LOGGER.warning(
            "stripe.payment.succeeded: no user for customer_id=%s",
            customer_id,
        )
        return

    # Update subscription to active
    user.subscription_status = "active"
    db.session.commit()
    LOGGER.info(
        "stripe.payment.succeeded: committed clerk_user_id=%s status=active",
        user.clerk_user_id,
    )

    log_subscription_event(
        user_id=user.id,
        event_type="renewed",
        stripe_event_id=_so_get(data, "id"),
        stripe_subscription_id=subscription_id,
        stripe_customer_id=customer_id,
        new_status="active",
    )


def _handle_payment_failed(data):
    """Handle failed payment."""
    customer_id = _so_get(data, "customer")
    subscription_id = _so_get(data, "subscription")

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return

    # Mark as past due
    old_status = user.subscription_status
    update_subscription(
        user_id=user.id,
        status="past_due",
    )

    log_subscription_event(
        user_id=user.id,
        event_type="payment_failed",
        stripe_event_id=_so_get(data, "id"),
        stripe_subscription_id=subscription_id,
        stripe_customer_id=customer_id,
        old_status=old_status,
        new_status="past_due",
    )
