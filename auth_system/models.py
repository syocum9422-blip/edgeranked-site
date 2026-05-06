"""
Database models for user authentication and subscription tracking.
Uses SQLAlchemy for database operations.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

ET = ZoneInfo("America/New_York")


class User(db.Model):
    """
    User model tracking Clerk authentication and Stripe subscription.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    clerk_user_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ET))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(ET), onupdate=lambda: datetime.now(ET))

    # Stripe subscription fields
    stripe_customer_id = db.Column(db.String(255), unique=True, index=True)
    stripe_subscription_id = db.Column(db.String(255), unique=True, index=True)
    subscription_status = db.Column(db.String(50), default="inactive")  # active, inactive, past_due, canceled
    subscription_plan = db.Column(db.String(50), default="monthly")  # monthly, annual
    subscription_current_period_end = db.Column(db.DateTime)

    # Subscription history
    subscribed_at = db.Column(db.DateTime)
    canceled_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def is_subscribed(self):
        """Check if user has active subscription."""
        if self.subscription_status != "active":
            return False
        if self.subscription_current_period_end:
            return self.subscription_current_period_end > datetime.now(ET)
        return False

    def to_dict(self):
        """Convert user to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "clerk_user_id": self.clerk_user_id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "is_subscribed": self.is_subscribed,
            "subscription_status": self.subscription_status,
            "subscription_plan": self.subscription_plan,
            "subscription_current_period_end": (
                self.subscription_current_period_end.isoformat()
                if self.subscription_current_period_end else None
            ),
        }


class SubscriptionEvent(db.Model):
    """
    Log of subscription-related events for audit trail.
    """
    __tablename__ = "subscription_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)  # created, renewed, canceled, updated
    stripe_event_id = db.Column(db.String(255), unique=True)
    stripe_subscription_id = db.Column(db.String(255))
    stripe_customer_id = db.Column(db.String(255))
    old_status = db.Column(db.String(50))
    new_status = db.Column(db.String(50))
    amount_cents = db.Column(db.Integer)
    currency = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(ET))
    raw_data = db.Column(db.Text)  # JSON blob of full event

    def __repr__(self):
        return f"<SubscriptionEvent {self.event_type} for user {self.user_id}>"


def init_db(app):
    """
    Initialize database with Flask app.
    Call this from create_app() in app.py.

    Usage:
        from auth_system.models import db, init_db
        db.init_app(app)
        with app.app_context():
            init_db(app)
    """
    db_path = os.environ.get("DATABASE_PATH", "edgeranked.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    db.init_app(app)

    with app.app_context():
        db.create_all()


def get_user_by_clerk_id(clerk_user_id):
    """Get user by Clerk user ID."""
    return User.query.filter_by(clerk_user_id=clerk_user_id).first()


def get_user_by_stripe_customer(stripe_customer_id):
    """Get user by Stripe customer ID."""
    return User.query.filter_by(stripe_customer_id=stripe_customer_id).first()


def get_user_by_email(email):
    """Get user by email address."""
    return User.query.filter_by(email=email).first()


def create_or_update_user(clerk_user_id, email, first_name=None, last_name=None):
    """
    Create new user or update existing user from Clerk data.
    """
    user = get_user_by_clerk_id(clerk_user_id)
    if user:
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.updated_at = datetime.now(ET)
    else:
        user = User(
            clerk_user_id=clerk_user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        db.session.add(user)

    db.session.commit()
    return user


def update_subscription(user_id, stripe_customer_id=None, stripe_subscription_id=None,
                         status=None, plan=None, period_end=None):
    """
    Update user's subscription information from Stripe webhook.
    """
    user = User.query.get(user_id)
    if not user:
        return None

    if stripe_customer_id:
        user.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        user.stripe_subscription_id = stripe_subscription_id
    if status:
        old_status = user.subscription_status
        user.subscription_status = status
        if status == "active" and old_status != "active":
            user.subscribed_at = datetime.now(ET)
        elif status in ("canceled", "inactive") and old_status == "active":
            user.canceled_at = datetime.now(ET)
    if plan:
        user.subscription_plan = plan
    if period_end:
        user.subscription_current_period_end = period_end

    user.updated_at = datetime.now(ET)
    db.session.commit()
    return user


def log_subscription_event(user_id, event_type, stripe_event_id=None,
                           stripe_subscription_id=None, stripe_customer_id=None,
                           old_status=None, new_status=None, amount_cents=None,
                           currency="usd", raw_data=None):
    """
    Log a subscription event for audit trail.
    """
    event = SubscriptionEvent(
        user_id=user_id,
        event_type=event_type,
        stripe_event_id=stripe_event_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
        old_status=old_status,
        new_status=new_status,
        amount_cents=amount_cents,
        currency=currency,
        raw_data=raw_data,
    )
    db.session.add(event)
    db.session.commit()
    return event