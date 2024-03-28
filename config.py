#config.py
import os
import subprocess
import plaid
import json
import urllib.parse

def get_secret(secret_id):
    try:
        # Use bws to fetch the secret by ID
        output = subprocess.check_output(['bws', 'secret', 'get', secret_id], text=True)
        secret = json.loads(output)
        # Extract and decode the password or connection string from the secret value
        decoded_value = urllib.parse.unquote(secret['value'])
        return decoded_value
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Failed to retrieve secret from Bitwarden: {str(e)}")


def get_database_uri():
    branch = os.getenv('FLASK_ENV', 'dev') 
    print('Detected branch: ', branch)

    # Map environment to the respective secret ID in Bitwarden
    secret_ids = {
        'dev': 'b2a63183-bf49-4705-839e-b141013a5e40',
        'stag': 'df9103ce-25a0-429c-8b50-b1410139eba4',
        'main': '94cb8775-54a4-4e62-814e-b1410139c1df'
    }

    if branch in secret_ids:
        password = get_secret(secret_ids[branch])
        # Bitwarden stores the entire connection string as the secret value
        return password
    else:
        raise ValueError(f"Invalid environment: {branch}")

class Config:
 
    SQLALCHEMY_DATABASE_URI = get_database_uri()

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'LaT!erraDe10lvido'  # Replace with a real secret key
    ENCRYPTION_KEY = b'udMS0kDG5aCdF1c9BeJErPhlpWKxkkdc8aRKP-OJihg='

    # Plaid credentials
    PLAID_CLIENT_ID = '654b9624dc1010001ce0fc03'
    PLAID_SECRET = '10ccc66e6281356b9de1e6d2197e46'
    PLAID_ENV = 'development'  # or 'sandbox', 'production'
    
    #MAIL_SERVER = 'srv469975.hstgr.cloud'
    #MAIL_PORT = 587
    #MAIL_USE_TLS = True
    #MAIL_USE_SSL = False
    #MAIL_USERNAME = 'manuel@automatos.ca'
    #MAIL_PASSWORD = '2!3prP8&!V4E&ak'

    MAIL_SERVER = 'sandbox.smtp.mailtrap.io'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = '357e33875489f2'
    MAIL_PASSWORD = '17e9824f02ffe1'

    # Select the appropriate environment
    @staticmethod
    def get_plaid_environment():
        if Config.PLAID_ENV == 'sandbox':
            return plaid.Environment.Sandbox
        elif Config.PLAID_ENV == 'development':
            return plaid.Environment.Development
        else:  # Assume production
            return plaid.Environment.Production