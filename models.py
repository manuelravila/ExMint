#models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy_utils import EncryptedType
from werkzeug.security import generate_password_hash
import datetime
from config import Config

db = SQLAlchemy()
key = Config.ENCRYPTION_KEY

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Removed: username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    credentials = db.relationship('Credential', backref='user', lazy=True)
    status = db.Column(db.String(20), nullable=False, default='Active')
    role = db.Column(db.String(20), nullable=False, default='User')

    # Relationship with Subscription
    subscriptions = db.relationship('Subscription', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def __repr__(self):
        return f'<User {self.email}>'

class Credential(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(100), nullable=False) 
    status = db.Column(db.String(10), nullable=False, default='Active')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    institution_name = db.Column(db.String(100))
    access_token = db.Column(EncryptedType(db.String, key))
    requires_update = db.Column(db.Boolean, default=False, nullable=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False, default='Active')
    credential_id = db.Column(db.Integer, db.ForeignKey('credential.id'), nullable=False)
    plaid_account_id = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100))  # e.g., 'Checking Account', 'Savings Account'
    type = db.Column(db.String(50))  # e.g., 'depository', 'credit'
    subtype = db.Column(db.String(50))  # e.g., 'checking', 'savings', 'credit card'
    mask = db.Column(db.String(4))  # Last 4 digits of the account number, if available
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Relation to Credential
    credential = db.relationship('Credential', backref=db.backref('accounts', lazy=True))

class PlaidTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.datetime.now(datetime.timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_ip = db.Column(db.String(45), nullable=False)  # Standard length to accommodate IPv6
    credential_id = db.Column(db.Integer, db.ForeignKey('credential.id'), nullable=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    operation = db.Column(db.String(100))  # e.g., 'token creation', 'institution refresh'
    response = db.Column(db.Text)  # Stores the response from Plaid
    posted_transactions = db.Column(db.Integer, nullable=True)  # Number of posted transactions
    pending_transactions = db.Column(db.Integer, nullable=True)  # Number of pending transactions

    # Relationship to Credential and Account
    credential = db.relationship('Credential', backref='plaid_transactions', lazy=True)
    account = db.relationship('Account', backref='plaid_transactions', lazy=True)

    def __repr__(self):
        return '<PlaidTransaction %r>' % self.id

class Subscription(db.Model):
    __tablename__ = 'subscription'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Tier properties: 1, 2, 5, or 12 (for VIP, tier_limit should be 12)
    tier_limit = db.Column(db.Integer, nullable=False)
    # Price in cents. For VIP subscriptions, set to 0.
    price_cents = db.Column(db.Integer, nullable=False)
    # Billing interval: 'monthly' or 'yearly'
    billing_interval = db.Column(db.String(10), nullable=False)
    # Subscription status: e.g., 'active' or 'inactive'
    status = db.Column(db.String(20), nullable=False, default='active')
    # When the subscription started
    start_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    # When the next billing/renewal is due
    renewal_date = db.Column(db.DateTime, nullable=False)
    # If the user cancels mid-cycle, store the cancellation date
    cancellation_date = db.Column(db.DateTime, nullable=True)
    # Number of billing periods that are waived (e.g., 1 for the free trial)
    waived_periods = db.Column(db.Integer, nullable=False, default=0)
    # Stripe integration fields (nullable if not applicable)
    stripe_subscription_id = db.Column(db.String(100), nullable=True)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    # When the Terms of Service were accepted
    tos_accepted_at = db.Column(db.DateTime, nullable=True)
    # Optionally, a flag to quickly check VIP status
    is_vip = db.Column(db.Boolean, nullable=False, default=False)
    
    def __repr__(self):
        return f'<Subscription {self.id} for User {self.user_id}>'
