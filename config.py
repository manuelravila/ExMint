#config.py
import os
import subprocess
import plaid
import json
import time
from urllib.parse import quote_plus

branch = os.getenv('FLASK_ENV', 'dev') 
bws_session = os.getenv('BWS_ACCESS_TOKEN')
if not bws_session:
    raise EnvironmentError("BWS_ACCESS_TOKEN environment variable not set.")

# Global cache dictionary
SECRETS_CACHE = {}
CACHE_EXPIRATION_SECONDS = 300  # Cache expiration time (5 minutes)

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

    current_time = time.time()
    cache_key = (secret_key, field_name)  # Use a tuple of secret_key and field_name as the cache key

    # Check if the secret is in the cache and hasn't expired
    if cache_key in SECRETS_CACHE and current_time < SECRETS_CACHE[cache_key]['expires']:
        return SECRETS_CACHE[cache_key]['value']

    try:
        # List all secrets using bws CLI
        output = subprocess.check_output(['bws', 'secret', 'list'], text=True)
        secrets = json.loads(output)

        # Convert secret_key to lowercase for case-insensitive comparison
        secret_key_lower = secret_key.lower()
        
        # Find the secret with the matching key
        secret = next((s for s in secrets if s['key'].lower() == secret_key_lower), None)
        if not secret:
            raise ValueError(f"Secret with key '{secret_key}' not found.")
        
        # Determine the value to return
        value_to_return = secret.get(field_name) if field_name else secret['value']
        
        # Update the cache with the new value
        SECRETS_CACHE[cache_key] = {
            'value': value_to_return,
            'expires': current_time + CACHE_EXPIRATION_SECONDS
        }

        return value_to_return
    
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Failed to list or retrieve secret from Secret Store: {str(e)}")

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

    ENCRYPTION_KEY = get_bw_secret('ENCRYPTION_KEY')

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