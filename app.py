# app.py
from flask import Flask, session, request, jsonify, redirect, url_for
import os
from extensions import mail
from config import Config
from models import db
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, current_user, logout_user
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

    # API-friendly unauthorized handler (returns JSON 401 instead of 302 redirect)
    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import request as _req, jsonify as _jsonify, redirect as _redirect, url_for as _url_for
        if _req.path.startswith('/api/'):
            return _jsonify({'error': 'Authentication required. Please log in again.'}), 401
        # For non-API routes, redirect to login page (Flask-Login default behavior)
        return _redirect(_url_for(login_manager.login_view, next=_req.path))

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
    from api_views import api_v1 as api_v1_blueprint
    app.register_blueprint(views_blueprint)
    app.register_blueprint(core_blueprint)
    app.register_blueprint(api_v1_blueprint)

    @app.before_request
    def before_request():
        session.permanent = True
        # Server-side session hard ceiling: force re-login if LOGIN_SESSION_DURATION
        # has elapsed since the login timestamp, regardless of sliding cookie refresh.
        if current_user.is_authenticated:
            login_time_str = session.get('_login_time')
            if login_time_str:
                try:
                    login_time = datetime.fromisoformat(login_time_str)
                    max_age = app.config.get('LOGIN_SESSION_DURATION', 14400)
                    elapsed = (datetime.utcnow() - login_time).total_seconds()
                    if elapsed > max_age:
                        logout_user()
                        session.clear()
                        if request.path.startswith('/api/'):
                            return jsonify({'error': 'Session expired. Please log in again.'}), 401
                        return redirect(url_for('views.login', next=request.path))
                except (ValueError, TypeError):
                    pass  # Malformed timestamp — let Flask-Login handle normally

            # Idle timeout: if no request received in IDLE_SESSION_DURATION seconds,
            # force re-login. Updates _last_active on every request so the timer
            # resets on each interaction.
            last_active_str = session.get('_last_active')
            if last_active_str:
                try:
                    last_active = datetime.fromisoformat(last_active_str)
                    idle_timeout = app.config.get('IDLE_SESSION_DURATION', 1800)
                    idle_elapsed = (datetime.utcnow() - last_active).total_seconds()
                    if idle_elapsed > idle_timeout:
                        logout_user()
                        session.clear()
                        if request.path.startswith('/api/'):
                            return jsonify({'error': 'Session expired due to inactivity. Please log in again.'}), 401
                        return redirect(url_for('views.login', next=request.path))
                except (ValueError, TypeError):
                    pass

            # Stamp last activity time for idle timeout tracking
            session['_last_active'] = datetime.utcnow().isoformat()

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
        
