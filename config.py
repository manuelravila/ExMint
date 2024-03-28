#config.py
import os
import plaid

basedir = os.path.abspath(os.path.dirname(__file__))

def get_database_uri(branch):
    print('Detected branch: ', branch)
    if branch == 'dev':
        return 'mysql+pymysql://mrar1995_xmnt_dev:c*36^PtDNf%n*F7@127.0.0.1:3307/mrar1995_xmnt_dev_db'
    elif branch == 'stag':
        return 'mysql+pymysql://mrar1995_xmnt_stg:94@GvRGo%2JzaVC@127.0.0.1:3306/mrar1995_xmnt_stg_db'
    elif branch == 'main':
        return 'mysql+pymysql://mrar1995_xmnt_prd:u#N4KHC5S!*3jBL@127.0.0.1:3306/mrar1995_xmnt_prd_db'
    else:
        raise ValueError(f"Invalid branch: {branch}")

class Config:
    # Detect the current Git branch
    git_branch = os.popen('git rev-parse --abbrev-ref HEAD').read().strip()
    
    SQLALCHEMY_DATABASE_URI = get_database_uri(git_branch)
    print('Selected Database: ', SQLALCHEMY_DATABASE_URI)

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