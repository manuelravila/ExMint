#config.py
import plaid, os
from urllib.parse import quote_plus
from secrets_manager import get_secret, branch

def get_database_uri():
    branch_trimmed = branch.strip()
    print('Detected branch: ', branch_trimmed)

    # Map environment to the respective secret ID in Bitwarden
    secret_keys = {
        'dev': 'xmnt_dev_db',
        'stag': 'xmnt_stg_db',
        'main': 'xmnt_prd_db'
    }

    if branch_trimmed in secret_keys:
        # Fetch and URL encode the password
        password = quote_plus(get_secret(secret_keys[branch_trimmed]))
        
        if branch_trimmed == 'dev':
            return f'mysql+pymysql://mrar1995_xmnt_dev:{password}@127.0.0.1:3307/mrar1995_xmnt_dev_db'
        elif branch_trimmed == 'stag':
            return f'mysql+pymysql://mrar1995_xmnt_stg:{password}@db-host:3306/mrar1995_xmnt_stg_db'
        elif branch_trimmed == 'main':
            if os.getenv('FLASK_SYS', '').lower() == 'windows':
                return f'mysql+pymysql://mrar1995_xmnt_prd:{password}@127.0.0.1:3307/mrar1995_xmnt_prd_db'
            else:
                return f'mysql+pymysql://mrar1995_xmnt_prd:{password}@db-host:3306/mrar1995_xmnt_prd_db'
        else:
            raise ValueError(f"Invalid branch: {branch_trimmed}")
    else:
        raise ValueError(f"Secret Key for the branch '{branch_trimmed}' not found")

class Config:

    SQLALCHEMY_DATABASE_URI = get_database_uri()

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = get_secret('SECRET_KEY') 
    ENCRYPTION_KEY = get_secret('ENCRYPTION_KEY')
    # Session cookie settings
    SESSION_COOKIE_SAMESITE = None
    SESSION_COOKIE_SECURE = True

    # Plaid credentials
    PLAID_CLIENT_ID = get_secret('PLAID_CLIENT_ID')
    PLAID_SECRET = get_secret('PLAID_SECRET')
    PLAID_WEBHOOK_URL = os.getenv('PLAID_WEBHOOK_URL')
    
    # Email configuration
    # TODO: Update external_redirect method with the new base URL
    # @staticmethod
    # def external_redirect(path=''):
    #     base_url = 'https://your_new_base_url/app'
    #     return f"{base_url}{Config.SUFFIX}/{path}"
