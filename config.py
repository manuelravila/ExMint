# config.py
import plaid
import os
from urllib.parse import quote_plus
from secrets_manager import get_secret, branch


def _get_db_password(branch_trimmed):
    """Get the database password.

    Community path: set DB_PASSWORD env var.
    Maintainer path: fetched from Bitwarden via environment-specific key.
    """
    direct = os.getenv("DB_PASSWORD")
    if direct:
        return direct
    bws_key_map = {"dev": "xmnt_dev_db", "stag": "xmnt_stg_db", "main": "xmnt_prd_db"}
    return get_secret(bws_key_map.get(branch_trimmed, "DB_PASSWORD"))


def get_database_uri():
    branch_trimmed = branch.strip()

    db_user = os.getenv("DB_USER")
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_name = os.getenv("DB_NAME")

    # Port default: 3307 for dev (SSH tunnel), 3306 for stag/main
    default_port = "3307" if branch_trimmed == "dev" else "3306"
    db_port = os.getenv("DB_PORT", default_port)

    if not db_user or not db_name:
        raise ValueError("DB_USER and DB_NAME environment variables must be set.")

    password = quote_plus(_get_db_password(branch_trimmed))
    return f"mysql+pymysql://{db_user}:{password}@{db_host}:{db_port}/{db_name}"


class Config:
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = get_secret("SECRET_KEY")
    ENCRYPTION_KEY = get_secret("ENCRYPTION_KEY")

    # Environment-dependent configuration (must come before session cookie
    # settings so SSL_CONTEXT is defined when those are evaluated)
    if branch.strip() == "main":
        PLAID_ENV = "production"
        SUFFIX = ""
        DEBUG = False
        SSL_CONTEXT = None
    elif branch.strip() == "stag":
        PLAID_ENV = "sandbox"
        DEBUG = True
        SUFFIX = "-stg"
        SSL_CONTEXT = None
    else:
        PLAID_ENV = "sandbox"
        DEBUG = True
        SUFFIX = "-dev"
        # SSL only enabled in dev when cert files are present
        _cert = os.getenv("SSL_CERT_PATH", "/app/dev_exmint_me.crt")
        _key = os.getenv("SSL_KEY_PATH", "/app/dev_exmint_me.key")
        SSL_CONTEXT = (_cert, _key) if os.path.exists(_cert) and os.path.exists(_key) else None

    # Session cookie settings
    # SECURE=True and SAMESITE=None are required for HTTPS deployments.
    # In dev without SSL, SECURE must be False or the browser silently drops
    # the cookie, causing a login loop.
    _ssl_active = SSL_CONTEXT is not None
    SESSION_COOKIE_SECURE = _ssl_active
    SESSION_COOKIE_SAMESITE = "None" if _ssl_active else "Lax"
    SESSION_COOKIE_PATH = "/"
    PERMANENT_SESSION_LIFETIME = 900  # 15 minutes

    # Plaid credentials
    PLAID_CLIENT_ID = get_secret("PLAID_CLIENT_ID")
    PLAID_SECRET = get_secret("PLAID_SECRET")
    PLAID_WEBHOOK_URL = os.getenv("PLAID_WEBHOOK_URL")

    # Email configuration
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = get_secret("MAIL_PASSWORD")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False

    # Admin
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', '')

    @staticmethod
    def get_plaid_environment():
        if Config.PLAID_ENV == "sandbox":
            return plaid.Environment.Sandbox
        elif Config.PLAID_ENV == "development":
            return plaid.Environment.Development
        else:
            return plaid.Environment.Production

    @staticmethod
    def external_redirect(path=""):
        base_url = os.getenv("APP_BASE_URL", "http://localhost:5000")
        return f"{base_url}/{path}"
