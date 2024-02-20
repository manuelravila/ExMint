#models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy_utils import EncryptedType
import jwt
import datetime
from flask import request
from config import Config

db = SQLAlchemy()
key = Config.ENCRYPTION_KEY

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    credentials = db.relationship('Credential', backref='user', lazy=True)
    status = db.Column(db.String(20), nullable=False, default='Active')
    role = db.Column(db.String(20), nullable=False, default='User')

    token = db.Column(EncryptedType(db.String, key))

    def generate_auth_token(self):
        payload = {
            'user_id': self.id,
            'iat': datetime.datetime.utcnow()  # Add issued-at time
        }
        new_token = jwt.encode(
            payload,
            Config.SECRET_KEY,
            algorithm='HS256'
        )

        self.token = new_token

        db.session.commit()
        return new_token
    
    @staticmethod
    def verify_auth_token(token):
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            user_id = payload['user_id']
            if User.query.get(user_id) is not None:
                return user_id
            return None
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    def __repr__(self):
        return '<User %r>' % self.username

class Credential(db.Model):
    id = db.Column(db.Integer, primary_key=True)
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
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
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
