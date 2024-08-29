# app.py
from flask import Flask
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

    print(f"Using database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Initialize extensions
    print('Initializing extensions')
    mail.init_app(app)
    flask_bcrypt.init_app(app)
    login_manager.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)

    # Configure CORS
    print('Configuring CORS')
    cors_origins = [
        "https://localhost:3000",  # Local dev URL
        "https://dev.exmint.me:3000",  # Local dev URL
        "https://127.0.0.1:3000",  # Local dev URL
        "https://stg-addin.exmint.me",  # Staging URL
        "https://addin.exmint.me",  # Production URL
        "https://exmint.me"  # Production WP URL
    ]

    CORS(app, resources={r"/*": {"origins": cors_origins}}, supports_credentials=True, allow_headers=[
        'Content-Type', 
        'Authorization', 
        'X-Requested-With',
        'X-Request-Source',
        'x-user-token',
        'cursors'
    ], allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

    # Initialize Plaid client
    print('Initializing Plaid')
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
    print('Registering blueprints')
    from views import views as views_blueprint
    from core_views import core as core_blueprint
    app.register_blueprint(views_blueprint)
    app.register_blueprint(core_blueprint)

    # Inject version and year into templates
    @app.context_processor
    def inject_version_and_year():
        return {'config': {'VERSION': VERSION}, 'current_year': datetime.now().year}

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return User.query.get(int(user_id))

    # Pass the Plaid client to the core_routes blueprint
    app.plaid_client = plaid_client

    print(f"App created with DEBUG={app.config['DEBUG']}, SSL_CONTEXT={app.config['SSL_CONTEXT']}")
    return app

app = create_app()

if __name__ == '__main__':
    if app.config['SSL_CONTEXT']:
        print('ExMint Back-End starting on SSL')
        app.run(ssl_context=app.config['SSL_CONTEXT'], debug=app.config['DEBUG'], host='0.0.0.0')
    else:
        print('ExMint Back-End starting without SSL')
        app.run(debug=app.config['DEBUG'], host='0.0.0.0')
        