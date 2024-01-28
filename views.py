# views.py
from flask import render_template, redirect, url_for, flash, request, jsonify, Blueprint, session
from flask_login import login_user, current_user, logout_user, login_required
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
        return redirect(url_for('main.dashboard'))
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
    return redirect(url_for('main.index'))

@views.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('views.index'))

@views.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # If the user is already logged in, redirect them to the dashboard
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))

    # If this is a POST request, handle the form submission here
    # (e.g., verify the email, send a reset link, etc.)
    if request.method == 'POST':
        # Implement the logic to handle password reset
        # ...
        flash('Password reset instructions have been sent to your email.', 'info')
        return redirect(url_for('views.login'))

    # For a GET request, simply render the reset password form
    return render_template('reset_password.html')

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

