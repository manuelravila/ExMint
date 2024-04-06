# views.py
from flask import current_app, render_template, redirect, url_for, flash, request, jsonify, Blueprint, session
from flask_login import login_user, current_user, logout_user, login_required
from extensions import mail
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from forms import LoginForm, RegistrationForm, ProfileForm
from models import User, db, Credential, Account
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

views = Blueprint('views', __name__)

@views.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        # Login logic...
        pass
    return render_template('index.html', form=form)

@views.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    user = current_user
    form = ProfileForm(obj=user)
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
    form = ProfileForm(is_registration=True)
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        try:
            user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password)
            db.session.add(user)
            db.session.commit()
            user.generate_auth_token()  # Generate and save the token
            flash('Your account has been created! You are now able to log in', 'success')
            return redirect(url_for('views.login'))
        except Exception as e:
            flash(str(e), 'danger')
            return render_template('register.html', form=form)

    return render_template('register.html', title='Register', form=form)


@views.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))  # Make sure this is the correct endpoint
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = User.query.filter((User.username == form.login.data) | (User.email == form.login.data)).first()
            if user and check_password_hash(user.password_hash, form.password.data):
                login_user(user)
                return redirect(url_for('views.dashboard'))  # Make sure this is the correct endpoint
            else:
                flash('Login Unsuccessful. Please check email and password', 'danger')
        except Exception as e:
            flash(f'An error occurred: {e}', 'danger')
            # Optionally, log the error as well
    return render_template('index.html', form=form)

def logout():
    logout_user()
    return redirect(url_for('views.index'))

@views.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('views.index'))

@views.route('/reset_password', methods=['GET', 'POST'])
# Use https://mailtrap.io/ for email for now .
def reset_password():
    # If the user is already logged in, redirect them to the dashboard
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            # Generate a secure token
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = serializer.dumps(email, salt='email-reset-salt')
            
            # Prepare the password reset email
            msg = Message('Password Reset Request', 
                          sender=current_app.config['MAIL_USERNAME'], 
                          recipients=[email])
            reset_url = url_for('views.reset_password_token', token=token, _external=True)  # Make sure you have a route to handle this
            msg.body = f'Please click the following link to reset your password: {reset_url}'
            
            # Send the email
            try:
                mail.send(msg)
            except Exception as e:
                print(f'An error occurred: {e}')
            flash('Password reset instructions have been sent to your email.', 'info')
            return redirect(url_for('views.login'))
        else:
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
            return redirect(url_for('views.login'))
        
        # If the request method is POST, update the user's password
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            user.password_hash = generate_password_hash(new_password)  # Use Werkzeug's generate_password_hash
            db.session.commit()
            flash('Your password has been updated!', 'success')
            return redirect(url_for('views.login'))

        # If the request method is GET, show the reset password form
        return render_template('reset_password_token.html')  # Ensure you have this template

    except (SignatureExpired, BadSignature):
        flash('Invalid or expired reset token.', 'danger')
        return redirect(url_for('views.login'))

@views.route('/user-info', methods=['GET', 'POST'])
@login_required
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
