#config.py
import os
import plaid

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'ExMint.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'LaT!erraDe10lvido'  # Replace with a real secret key
    ENCRYPTION_KEY = b'udMS0kDG5aCdF1c9BeJErPhlpWKxkkdc8aRKP-OJihg='

    # Plaid credentials
    PLAID_CLIENT_ID = '654b9624dc1010001ce0fc03'
    PLAID_SECRET = '10ccc66e6281356b9de1e6d2197e46'
    PLAID_ENV = 'development'  # or 'sandbox', 'production'

    # Select the appropriate environment
    @staticmethod
    def get_plaid_environment():
        if Config.PLAID_ENV == 'sandbox':
            return plaid.Environment.Sandbox
        elif Config.PLAID_ENV == 'development':
            return plaid.Environment.Development
        else:  # Assume production
            return plaid.Environment.Production