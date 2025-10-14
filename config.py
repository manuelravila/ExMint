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
    MAIL_SERVER = 'mail.exmint.me'
    MAIL_USERNAME = 'noreply@exmint.me'
    MAIL_PASSWORD = get_secret('MAIL_PASSWORD')
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False  

    # --- ADDED BACK: Environment dependent configuration ---
    if branch.strip() == 'main':
        PLAID_ENV = 'production'
        SUFFIX = ''
        if os.getenv('FLASK_SYS', '').lower() == 'windows':
            SSL_CONTEXT = ('/dev_exmint_me.crt', '/dev_exmint_me.key')
            DEBUG = True
        else:
            SSL_CONTEXT = None
            DEBUG = False
    elif branch.strip() == 'stag':
        PLAID_ENV = 'sandbox'   
        DEBUG = True  
        SUFFIX = '-stg'
        SSL_CONTEXT = None
    else:
        PLAID_ENV = 'sandbox' 
        DEBUG = True
        SUFFIX = '-dev'
        SSL_CONTEXT = ('/app/dev_exmint_me.crt', '/app/dev_exmint_me.key')

    print(f"Current branch: {branch.strip()}")
    print(f"SSL_CONTEXT: {SSL_CONTEXT}")

    # --- ADDED BACK: Method to get the Plaid Environment ---
    @staticmethod
    def get_plaid_environment():
        if Config.PLAID_ENV == 'sandbox':
            return plaid.Environment.Sandbox
        elif Config.PLAID_ENV == 'development':
            return plaid.Environment.Development
        else:  # Assume production
            return plaid.Environment.Production
        
    # --- ADDED BACK: Method for external redirects with updated URL ---
    @staticmethod
    def external_redirect(path=''):
        # Using the new base URL for prod and appending suffix for staging
        base_url = 'https://exmint-app.automatos.ca'
        # For stag, suffix will be "-stg", resulting in exmint-app-stg...
        base_url = base_url.replace('exmint-app', f'exmint-app{Config.SUFFIX}')
        return f"{base_url}/{path}"