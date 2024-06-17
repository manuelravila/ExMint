#config.py
import os
import subprocess
import plaid
import json
import time
from urllib.parse import quote_plus
from secrets_manager import get_secret, branch

def get_database_uri():
    print('Detected branch: ', branch)

    # Map environment to the respective secret ID in Bitwarden
    secret_keys = {
        'dev': 'xmnt_dev_db',
        'stag': 'xmnt_stg_db',
        'main': 'xmnt_prd_db'
    }

    if branch in secret_keys:
        # Fetch and URL encode the password
        password = quote_plus(get_secret(secret_keys[branch]))
        
        if branch == 'dev':
            return f'mysql+pymysql://mrar1995_xmnt_dev:{password}@127.0.0.1:3307/mrar1995_xmnt_dev_db'
        elif branch == 'stag':
            return f'mysql+pymysql://mrar1995_xmnt_stg:{password}@127.0.0.1:3306/mrar1995_xmnt_stg_db'
        elif branch == 'main':
            return f'mysql+pymysql://mrar1995_xmnt_prd:{password}@127.0.0.1:3306/mrar1995_xmnt_prd_db'
        else:
            raise ValueError(f"Invalid branch: {branch}")
    else:
        raise ValueError(f"Secret Key for the branch '{branch}' not found")

class Config:

    SQLALCHEMY_DATABASE_URI = get_database_uri()

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = get_secret('SECRET_KEY') 

    ENCRYPTION_KEY = get_secret('ENCRYPTION_KEY')

    # Plaid credentials
    PLAID_CLIENT_ID = get_secret('PLAID_CLIENT_ID')
    PLAID_SECRET = get_secret('PLAID_SECRET')
    if branch == 'main':
        PLAID_ENV = 'production'
        MAIL_SERVER = 'mail.exmint.me'
        MAIL_USERNAME = 'admin@exmint.me'
    else:
        PLAID_ENV = 'sandbox' 
        MAIL_SERVER = 'sandbox.smtp.mailtrap.io'
        MAIL_USERNAME = '357e33875489f2'

    MAIL_PASSWORD = get_secret('MAIL_PASSWORD')
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False

    # Select the appropriate environment
    @staticmethod
    def get_plaid_environment():
        if Config.PLAID_ENV == 'sandbox':
            return plaid.Environment.Sandbox
        elif Config.PLAID_ENV == 'development':
            return plaid.Environment.Development
        else:  # Assume production
            return plaid.Environment.Production