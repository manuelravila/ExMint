#models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy_utils import EncryptedType
from werkzeug.security import generate_password_hash
import datetime
from config import Config

db = SQLAlchemy()
key = Config.ENCRYPTION_KEY

class CustomCategory(db.Model):
    __tablename__ = 'custom_categories'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_custom_categories_user_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    color = db.Column(db.String(7), nullable=False, default='#2C6B4F')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = db.relationship('User', backref=db.backref('custom_categories', lazy=True))
    transactions = db.relationship('Transaction', back_populates='custom_category', lazy=True)
    overrides = db.relationship('TransactionCategoryOverride', back_populates='custom_category', lazy=True)
    rules = db.relationship('CategoryRule', back_populates='category', lazy=True)

    def __repr__(self):
        return f'<CustomCategory {self.name}>'


class CategoryRule(db.Model):
    __tablename__ = 'category_rules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('custom_categories.id', ondelete='CASCADE'), nullable=False)
    text_to_match = db.Column(db.String(512), nullable=False)
    field_to_match = db.Column(db.String(50), nullable=False, default='description')
    transaction_type = db.Column(db.String(20), nullable=True)
    amount_min = db.Column(db.Numeric(14, 2), nullable=True)
    amount_max = db.Column(db.Numeric(14, 2), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = db.relationship('User', backref=db.backref('category_rules', lazy=True))
    category = db.relationship('CustomCategory', back_populates='rules', lazy=True)

    def __repr__(self):
        return f'<CategoryRule {self.text_to_match} -> {self.category_id}>'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Removed: username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    credentials = db.relationship('Credential', backref='user', lazy=True)
    status = db.Column(db.String(20), nullable=False, default='Active')
    role = db.Column(db.String(20), nullable=False, default='User')

    transactions = db.relationship('Transaction', backref='user', lazy=True)
    budgets = db.relationship('Budget', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def __repr__(self):
        return f'<User {self.email}>'

class Credential(db.Model):
    __table_args__ = (
        db.UniqueConstraint('user_id', 'item_id', name='uq_credential_user_item_id'),
    )

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
    custom_category_id = db.Column(db.Integer, db.ForeignKey('custom_categories.id'), nullable=True)
    parent_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    is_split_child = db.Column(db.Boolean, nullable=False, default=False)
    has_split_children = db.Column(db.Boolean, nullable=False, default=False)
    is_new = db.Column(db.Boolean, nullable=False, default=True)
    seen_by_user = db.Column(db.Boolean, nullable=False, default=False)
    last_seen_by_user = db.Column(db.DateTime, nullable=True)

    credential = db.relationship('Credential', backref=db.backref('transactions', lazy=True))
    custom_category = db.relationship('CustomCategory', back_populates='transactions', lazy=True)
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
    custom_category_id = db.Column(db.Integer, db.ForeignKey('custom_categories.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    transaction = db.relationship('Transaction', backref=db.backref('manual_override_record', uselist=False, cascade='all, delete-orphan'))
    custom_category = db.relationship('CustomCategory', back_populates='overrides', lazy=True)

class AppSetting(db.Model):
    """Key-value store for admin-controlled application settings."""
    __tablename__ = 'app_settings'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=False)


def get_app_setting(key, default=''):
    """Return the value of an AppSetting, or *default* if not found or DB unavailable."""
    try:
        s = db.session.get(AppSetting, key)
        return s.value if s else default
    except Exception:
        return default


def set_app_setting(key, value):
    """Create or update an AppSetting row and commit."""
    s = db.session.get(AppSetting, key)
    if s:
        s.value = str(value)
    else:
        db.session.add(AppSetting(key=key, value=str(value)))
    db.session.commit()


class Budget(db.Model):
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_label = db.Column(db.String(255), nullable=False)
    frequency = db.Column(db.String(32), nullable=False, default='monthly')
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
