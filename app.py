# app.py
from flask import Flask, session
import os
from extensions import mail
from config import Config
from models import db
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_cors import CORS
import plaid
from plaid.api import plaid_api
from version import __version__ as VERSION
from datetime import datetime

# Initialize Extensions
migrate = Migrate()
flask_bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'views.login'

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    # Initialize extensions
    mail.init_app(app)
    flask_bcrypt.init_app(app)
    login_manager.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)

    # Configure CORS
    cors_origins = [
        "http://localhost:5000",  # Local dev URL without sandbox
        "http://127.0.0.1:5000",  # Local dev URL without sandbox
        "https://192.168.50.206:5000",  # Local dev URL without sandbox
        "https://localhost:3000",  # Local dev URL
        "https://dev.exmint.me:3000",  # Local dev URL
        "https://127.0.0.1:3000",  # Local dev URL
        "https://stg-addin.exmint.me",  # Staging URL
        "https://addin.exmint.me",  # Production URL
        "https://exmint.me"  # Production WP URL
    ]

    CORS(app, resources={r"/*": {"origins": cors_origins}}, supports_credentials=True, allow_headers=[
        'Content-Type',
        'X-Requested-With',
        'X-Request-Source',
        'cursors'
    ], allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])

    # Initialize Plaid client
    plaid_environment = Config.get_plaid_environment()
    configuration = plaid.Configuration(
        host=plaid_environment,
        api_key={
            'clientId': Config.PLAID_CLIENT_ID,
            'secret': Config.PLAID_SECRET,
        }
    )
    api_client = plaid.ApiClient(configuration)
    plaid_client = plaid_api.PlaidApi(api_client)

    # Register blueprints
    from views import views as views_blueprint
    from core_views import core as core_blueprint
    app.register_blueprint(views_blueprint)
    app.register_blueprint(core_blueprint)

    @app.before_request
    def before_request():
        session.permanent = True

    # Inject version and year into templates
    @app.context_processor
    def inject_version_and_year():
        return {'config': {'VERSION': VERSION}, 'current_year': datetime.now().year}

    # Inject registration_open into all templates
    @app.context_processor
    def inject_registration_open():
        from models import get_app_setting
        try:
            return {'registration_open': get_app_setting('registration_open', 'true') == 'true'}
        except Exception:
            return {'registration_open': True}

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return db.session.get(User, int(user_id))

    # Pass the Plaid client to the core_routes blueprint
    app.plaid_client = plaid_client

    # Set the APPLICATION_ROOT if running in the dev environment
    if os.environ.get('FLASK_ENV') == 'dev':
        app.config['APPLICATION_ROOT'] = '/sandbox'
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    return app

app = create_app()

if __name__ == '__main__':
    if app.config['SSL_CONTEXT']:
        app.run(ssl_context=app.config['SSL_CONTEXT'], debug=app.config['DEBUG'], host='0.0.0.0')
    else:
        app.run(debug=app.config['DEBUG'], host='0.0.0.0')
        
