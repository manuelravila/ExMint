# views.py
from flask import current_app, render_template, redirect, url_for, flash, request, jsonify, Blueprint, session, make_response, g
from flask_login import login_user, current_user, logout_user, login_required
from extensions import mail
from functools import wraps
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from forms import LoginForm, RegistrationForm, ProfileForm
from models import User, db, Credential, Account
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

views = Blueprint('views', __name__)

def combined_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if 'X-Request-Source' in request.headers and request.headers['X-Request-Source'] == 'Excel-Add-In':
            if 'Authorization' in request.headers:
                print('Decorator found header in request and Authorization in it')
                token = request.headers['Authorization'].split(" ")[1]
                user_id = User.verify_auth_token(token)
                if user_id:
                    user = User.query.get(user_id)
                    if user:
                        login_user(user)
                        return f(*args, **kwargs)
        else:
            token = request.cookies.get('token')
            print(f"Token found: {token}")  # Debug statement
            if token:
                user_id = User.verify_auth_token(token)
                if user_id:
                    user = User.query.get(user_id)
                    if user:
                        login_user(user)
                        return f(*args, **kwargs)

        return jsonify({'message': 'Unauthorized'}), 401

    return decorated_function

@views.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))
    return redirect(url_for('views.login'))

@views.route('/dashboard', methods=['GET', 'POST'])
@combined_required
def dashboard():
    
    user = current_user
    form = ProfileForm(obj=user)

    # Only set the token if the request is authenticated via token
    if request.headers.get('X-Request-Source') == 'Excel-Add-In' and 'Authorization' in request.headers:
        form.token.data = user.token

    # Check for open modals query parameter
    connections_modal_open = session.pop('connections_modal_open', False)
    modal_open = session.pop('modal_open', False)

    if form.validate_on_submit():
        if 'submit' in request.form:
            # Update user profile
            user.username = form.username.data
            user.email = form.email.data
            if form.password.data:
                user.set_password(form.password.data)  # Assuming you have a method to set password

            # Feedback message for profile update
            flash('Your profile has been updated!', 'success')

        elif 'regenerate_token' in request.form:
            # Logic to regenerate token
            new_token = user.generate_auth_token()
            form.token.data = new_token 
            flash('Token regenerated successfully!', 'success')
            session['modal_open'] = True  # Set session variable
            return redirect(url_for('views.dashboard', modal_open='true'))  # Add query parameter

        # Save changes to the database
        db.session.commit()

        # Clear the session variables
        session.pop('modal_open', None)  
        session.pop('connections_modal_open', None)

        return redirect(url_for('views.dashboard'))

    return render_template('dashboard.html', title='Dashboard', form=form, is_profile_update=True, modal_open=modal_open, connections_modal_open=connections_modal_open)

@views.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        try:
            user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password)
            db.session.add(user)
            db.session.commit()
            token = user.generate_auth_token()  # Generate and save the token
            login_user(user)  # Log in the user
            
            response = redirect(Config.external_redirect('dashboard'))
            response.set_cookie('token', token, 
                                httponly=True, 
                                secure=current_app.config['SESSION_COOKIE_SECURE'], 
                                samesite=current_app.config['SESSION_COOKIE_SAMESITE'])
            flash('Your account has been created! You are now logged in.', 'success')
            return response
        except Exception as e:
            flash(str(e), 'danger')
            return render_template('register.html', suffix=current_app.config['SUFFIX'], form=form)

    return render_template('register.html', title='Register', suffix=current_app.config['SUFFIX'], form=form)

@views.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        print('Current user IS authenticated')
        return handle_authenticated_user()

    if request.method == 'POST':
        return handle_login_request()

    form = LoginForm()
    return render_template('index.html', form=form)


def handle_login_request():
    # Distinguish between JSON and Form submissions
    try:
        data = request.get_json()
        username_or_email = data.get('login')
        password = data.get('password')
    except:
        username_or_email = request.form.get('login')
        password = request.form.get('password')

    # Authenticate the user
    if username_or_email and password:
        user = User.query.filter((User.username == username_or_email) | (User.email == username_or_email)).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            return handle_successful_login(user)
        else:
            error_message = 'Login Unsuccessful. Please check username and password'
    else:
        error_message = 'Login or password not provided'

    return handle_unsuccessful_login(error_message)


def handle_authenticated_user():
    # Decide response based on the source of the request
    if request.headers.get('X-Request-Source') == 'Excel-Add-In':
        return jsonify({'message': 'User already logged in'}), 200
    return redirect(url_for('views.dashboard'))


def handle_successful_login(user):
    print('SUCCESSFUL login initiated')
    if request.headers.get('X-Request-Source') == 'Excel-Add-In':
        token = user.generate_auth_token()
        return jsonify({'message': 'User logged in successfully', 'token': token}), 200
    else:
        # Set the token as a cookie in the response for web login
        print('Using secure cookies: ',current_app.config['SESSION_COOKIE_SECURE'])
        response = redirect(url_for('views.dashboard'))
        response.set_cookie('token', user.token, 
                            httponly=True, 
                            secure=current_app.config['SESSION_COOKIE_SECURE'], 
                            samesite=current_app.config['SESSION_COOKIE_SAMESITE'])
        print(response.headers)
        return response

def handle_unsuccessful_login(error_message):
    if request.headers.get('X-Request-Source') == 'Excel-Add-In':
        return jsonify({'message': error_message}), 401
    else:
        flash(error_message, 'danger')
        return redirect(url_for('views.login'))

@views.route('/logout', methods=['GET', 'POST'])
def logout():
    print(f"User logged in before logout: {current_user.is_authenticated}")
    logout_user()
    print(f"User logged out after logout: {not current_user.is_authenticated}")
    if request.method == 'POST':
        print("Request from Excel Add-in")
        return jsonify({'message': 'Logged out successfully'})
    else:
        print("Request from Flask UI")
        response = make_response(redirect(url_for('views.index')))

    # Add headers to clear localStorage on the client side
    response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'
        
    return response
        
@views.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # If the user is already logged in, redirect them to the dashboard
    if current_user.is_authenticated:
        #print("User is already authenticated, redirecting to dashboard.")
        return redirect(url_for('views.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        #print(f"Received POST request for password reset with email: {email}")

        user = User.query.filter_by(email=email).first()
        if user:
            print(f"User found: {user.email}")

            # Generate a secure token
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = serializer.dumps(email, salt='email-reset-salt')
            #print(f"Generated token: {token}")

            # Prepare the password reset email
            reset_url = url_for('views.reset_password_token', token=token, _external=True)
            #print(f"Generated reset URL: {reset_url}")

            html_content = render_template('password_reset_email.html', reset_url=reset_url, suffix=current_app.config['SUFFIX'])
            msg = Message('Password Reset Request', 
                          sender=current_app.config['MAIL_USERNAME'], 
                          recipients=[email])
            msg.html = html_content

            # Send the email
            try:
                mail.send(msg)
                print(f"Password reset email sent to: {email}")
            except Exception as e:
                print(f"An error occurred while sending the email: {e}")

            # Render the password reset sent page
            return render_template('password_reset_sent.html', suffix=current_app.config['SUFFIX'])
        else:
            print(f"No account found for email: {email}")
            flash('No account could be found for this email address.', 'warning')

    return render_template('reset_password.html')

@views.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    try:
        # Initialize the serializer
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        
        # Attempt to decode the token
        email = serializer.loads(token, salt='email-reset-salt', max_age=3600)  # Token expires after 1 hour
        
        # Find the user by email
        user = User.query.filter_by(email=email).first()
        if user is None:
            flash('Invalid or expired reset token.', 'danger')
            return redirect(Config.external_redirect())
        
        # If the request method is POST, update the user's password
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            user.password_hash = generate_password_hash(new_password)  # Use Werkzeug's generate_password_hash
            db.session.commit()
            flash('Your password has been updated!', 'success')
            return redirect(Config.external_redirect())

        # If the request method is GET, show the reset password form
        return render_template('reset_password_token.html')  # Ensure you have this template

    except (SignatureExpired, BadSignature):
        flash('Invalid or expired reset token.', 'danger')
        return redirect(Config.external_redirect())

@views.route('/user-info', methods=['GET', 'POST'])
@combined_required
def get_user_info():
    user = User.query.filter_by(id=current_user.id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    if request.method == 'POST' and request.json.get('renew_token'):
        user.generate_auth_token()  # Renew the token

    user_info = {
        "username": user.username,
        "email": user.email,
        "token": user.token # Return the token string directly
    }
    return jsonify(user_info)

@views.route('/api/accounts/enable/<int:account_id>', methods=['POST'])
def enable_account(account_id):
    account = Account.query.get(account_id)
    if account:
        account.is_enabled = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'Account enabled.'})
    return jsonify({'success': False, 'message': 'Account not found.'}), 404

@views.route('/api/accounts/disable/<int:account_id>', methods=['POST'])
def disable_account(account_id):
    account = Account.query.get(account_id)
    if account:
        account.is_enabled = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Account disabled.'})
    return jsonify({'success': False, 'message': 'Account not found.'}), 404