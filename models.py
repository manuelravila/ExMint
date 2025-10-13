#models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy_utils import EncryptedType
from werkzeug.security import generate_password_hash
import datetime
from config import Config

db = SQLAlchemy()
key = Config.ENCRYPTION_KEY

class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    label = db.Column(db.String(255), nullable=False)
    text_to_match = db.Column(db.String(512), nullable=False)
    field_to_match = db.Column(db.String(50), nullable=False, default='description')
    transaction_type = db.Column(db.String(20), nullable=True)
    amount_min = db.Column(db.Numeric(14, 2), nullable=True)
    amount_max = db.Column(db.Numeric(14, 2), nullable=True)
    color = db.Column(db.String(7), nullable=False, default='#2C6B4F')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationship to user and transactions
    user = db.relationship('User', backref=db.backref('categories', lazy=True))
    transactions = db.relationship('Transaction', back_populates='custom_category', lazy=True)

    def __repr__(self):
        return f'<Category {self.label}>'

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
    transactions = db.relationship('Transaction', backref='user', lazy=True)

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
    transactions_cursor = db.Column(db.String(512), nullable=True)

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
    transactions = db.relationship('Transaction', backref='account', lazy=True)

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

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    plaid_transaction_id = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    credential_id = db.Column(db.Integer, db.ForeignKey('credential.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    iso_currency_code = db.Column(db.String(10))
    category = db.Column(db.Text)
    merchant_name = db.Column(db.String(255))
    payment_channel = db.Column(db.String(50))
    date = db.Column(db.Date, nullable=False)
    pending = db.Column(db.Boolean, nullable=False, default=False)
    is_removed = db.Column(db.Boolean, nullable=False, default=False)
    last_action = db.Column(db.String(20), nullable=False, default='added')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    custom_category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    parent_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    is_split_child = db.Column(db.Boolean, nullable=False, default=False)
    has_split_children = db.Column(db.Boolean, nullable=False, default=False)

    credential = db.relationship('Credential', backref=db.backref('transactions', lazy=True))
    custom_category = db.relationship('Category', back_populates='transactions', lazy=True)
    parent_transaction = db.relationship(
        'Transaction',
        remote_side=[id],
        backref=db.backref('split_children', lazy='dynamic'),
        foreign_keys=[parent_transaction_id]
    )

    def __repr__(self):
        return f'<Transaction {self.plaid_transaction_id}>'


class TransactionCategoryOverride(db.Model):
    __tablename__ = 'transaction_category_override'

    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), primary_key=True)
    label = db.Column(db.String(255), nullable=False)
    color = db.Column(db.String(7), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    transaction = db.relationship('Transaction', backref=db.backref('manual_override_record', uselist=False, cascade='all, delete-orphan'))

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
