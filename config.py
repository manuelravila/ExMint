#config.py
import os
import subprocess
import plaid
import json
import base64
from urllib.parse import quote_plus

branch = os.getenv('FLASK_ENV', 'dev') 

def get_bw_secret(secret_key, field_name=None):
    """
    Retrieves a secret from Bitwarden Secrets Manager (BWS) based on a key.

    This function lists all secrets available to the service account associated with the
    BWS_SESSION environment variable, searches for the secret with the specified key (case-insensitive),
    and returns either the whole secret value or a specific field within that secret.

    Note: Two BWS service accounts are recommended - one for production and another for lower environments.
    The appropriate service account is automatically used based on the BWS_SESSION token set in environment variables,
    allowing for environment-appropriate secret retrieval without manual environment specification.

    Args:
        secret_key (str): The key of the secret to retrieve. Comparison is case-insensitive.
        field_name (str, optional): Specific field within the secret to retrieve. Defaults to None.

    Returns:
        str: The secret's value or the value of the specified field within the secret.

    Raises:
        ValueError: If the secret with the given key is not found or BWS retrieval fails.
    """
    try:
        # List all secrets using bws CLI
        output = subprocess.check_output(['bws', 'secret', 'list', '--session', os.getenv('BWS_SESSION')], text=True)
        secrets = json.loads(output)

        # Convert secret_key to lowercase for case-insensitive comparison
        secret_key_lower = secret_key.lower()
        
        # Find the secret with the matching key
        secret = next((s for s in secrets if s['key'].lower() == secret_key_lower), None)
        if not secret:
            raise ValueError(f"Secret with key '{secret_key}' not found.")
        
        # If a field name is specified, return that field
        if field_name:
            return secret.get(field_name)
        
        # Otherwise, return the secret's value
        return secret['value']
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Failed to list or retrieve secret from Bitwarden: {str(e)}")

def get_database_uri():
    """
    Constructs the database URI using secrets retrieved from Bitwarden Secrets Manager (BWS).

    This function dynamically constructs the database connection string based on the current Flask
    environment. It fetches the environment-specific database password from BWS, URL-encodes it,
    and incorporates it into the formatted database URI.

    Returns:
        str: The fully constructed database URI.

    Raises:
        ValueError: If the environment is invalid or the database password is not found in BWS.
    """    
    print('Detected branch: ', branch)

    # Map environment to the respective secret ID in Bitwarden
    secret_keys = {
        'dev': 'xmnt_dev_db',
        'stag': 'xmnt_stg_db',
        'main': 'xmnt_prd_db'
    }

    if branch in secret_keys:
        # Fetch and URL encode the password
        password = quote_plus(get_bw_secret(secret_keys[branch]))
        
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
    """
    Configuration class for the Flask application.

    This class encapsulates all configuration settings for the application, including database
    connection strings, security keys, Plaid credentials, and mail server settings. Sensitive
    information is dynamically retrieved from Bitwarden Secrets Manager (BWS) based on the
    current environment to ensure appropriate separation of production and lower environment secrets.

    The use of BWS and environment variables allows for secure, dynamic configuration without
    hard-coding sensitive information, adhering to best practices for application security and
    configuration management.
    """
 
    SQLALCHEMY_DATABASE_URI = get_database_uri()

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = get_bw_secret('SECRET_KEY') 
    ENCRYPTION_KEY = base64.b64decode(get_bw_secret('ENCRYPTION_KEY'))

    # Plaid credentials
    PLAID_CLIENT_ID = get_bw_secret('PLAID_CLIENT_ID')
    PLAID_SECRET = get_bw_secret('PLAID_SECRET')
    if branch == 'main':
        PLAID_ENV = 'production'
        MAIL_SERVER = 'mail.exmint.me'
        MAIL_USERNAME = 'admin@exmint.me'
    else:
        PLAID_ENV = 'development' # or 'sandbox'
        MAIL_SERVER = 'sandbox.smtp.mailtrap.io'
        MAIL_USERNAME = '357e33875489f2'

    MAIL_PASSWORD = get_bw_secret('MAIL_PASSWORD')
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