# views.py
from flask import current_app, render_template, redirect, url_for, flash, request, jsonify, Blueprint, session, make_response
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
    return redirect(url_for('views.login'))

def send_activation_email_to(email, subject):
    """
    Generates an activation token using 'email-activate-salt', builds the activation URL, and sends an activation email using Flask-Mail.
    """
    from itsdangerous import URLSafeTimedSerializer
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    activation_token = serializer.dumps(email, salt='email-activate-salt')
    activation_url = url_for('views.activate_account', token=activation_token, _external=True, suffix=current_app.config.get('SUFFIX', ''))
    
    html_content = render_template('activation_email.html', activation_url=activation_url, suffix=current_app.config.get('SUFFIX', ''))
    
    from flask_mail import Message
    msg = Message(subject,
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[email])
    msg.html = html_content
    try:
        mail.send(msg)
        print(f"Activation email sent to {email}")
        return True
    except Exception as e:
        current_app.logger.error("Error sending activation email: %s", e)
        return False


@views.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    user = current_user
    form = ProfileForm(obj=user)

    # Check for open modals query parameter
    connections_modal_open = session.pop('connections_modal_open', False)

    if form.validate_on_submit():
        if 'submit' in request.form:
            # If the email has changed, update email/username, mark user as pending, and send reactivation email
            if form.email.data != user.email:
                user.email = form.email.data
                user.status = 'Pending'
                
                if send_activation_email_to(user.email, "Re-Activate Your ExMint Account"):
                    flash("Your email has been changed. Please check your new email to re-activate your account.", "info")
                else:
                    flash("Error sending re-activation email. Please try again.", "danger")
            
            # Update password if provided
            if form.password.data:
                user.set_password(form.password.data)
            
            # (Ignore any changes to the username field)
            flash('Your profile has been updated!', 'success')

        db.session.commit()
        return redirect(url_for('views.dashboard'))

    return render_template('dashboard.html', title='Dashboard', form=form, is_profile_update=True, connections_modal_open=connections_modal_open)

@views.route('/dashboard-data', methods=['GET'])
@login_required
def dashboard_data():
    user = current_user

    # Retrieve the user’s banks from DB
    banks = Credential.query.filter_by(user_id=user.id, status='Active').all()

    # Build the JSON response
    banks_data = []
    for bank in banks:
        banks_data.append({
            'id': bank.id,
            'institution_name': bank.institution_name,
            'requires_update': bank.requires_update
        })

    return jsonify({'banks': banks_data})

@views.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        email = form.email.data
        hashed_password = generate_password_hash(form.password.data)
        
        # Create new user with status 'Pending'; set username to email temporarily
        user = User(email=email, password_hash=hashed_password, status='Pending')
        db.session.add(user)
        db.session.commit()
        
        # Generate and send activation email using the helper
        if not send_activation_email_to(email, "Activate Your ExMint Account"):
            flash("Error sending activation email. Please try again.", "danger")
            return redirect(url_for('views.register'))
        
        flash("Registration successful! Please check your email to activate your account.", "info")
        return redirect(url_for('views.login'))

    return render_template('register.html', title='Register', suffix=current_app.config.get('SUFFIX', ''), form=form)


@views.route('/activate/<token>')
def activate_account(token):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='email-activate-salt', max_age=86400)  # Token valid for 1 day
    except (SignatureExpired, BadSignature):
        flash("The activation link is invalid or has expired.", "danger")
        return redirect(url_for('views.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('views.register'))

    if user.status == "Active":
        flash("Your account is already active. You can log in directly.", "warning")
        return redirect(url_for('views.login'))

    # Update user status to Active
    user.status = "Active"
    db.session.commit()

    flash("Your account has been activated! You may now log in.", "success")
    return redirect(url_for('views.login'))

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
        user = User.query.filter(User.email == username_or_email).first()
        if user and check_password_hash(user.password_hash, password):
            # Check if user has activated their account
            if user.status != 'Active':  # Add this check
                error_message = 'Account not activated. Please check your email for the activation link.'
                return handle_unsuccessful_login(error_message)
            
            login_user(user, remember=False)
            return handle_successful_login(user)
        else:
            error_message = 'Login Unsuccessful. Please check email and password'
    else:
        error_message = 'Login or password not provided'

    return handle_unsuccessful_login(error_message)


def handle_authenticated_user():
    # Decide response based on the source of the request
    if request.is_json:
        return jsonify({'message': 'User already logged in'}), 200
    return redirect(url_for('views.dashboard'))


def handle_successful_login(user):
    if request.is_json:
        return jsonify({'message': 'User logged in successfully'}), 200

    next_page = request.args.get('next')
    return redirect(next_page or url_for('views.dashboard'))

def handle_unsuccessful_login(error_message):
    if request.is_json:
        return jsonify({'message': error_message}), 401
    else:
        flash(error_message, 'danger')
        return redirect(url_for('views.login'))

# views.py
@views.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    # Mark all transactions as seen before logging out
    transactions = Transaction.query.filter_by(user_id=current_user.id).all()
    for txn in transactions:
        txn.seen_by_user = True
        txn.is_new = False
    db.session.commit()

    logout_user()
    if request.is_json or request.method == 'POST':
        response = jsonify({'message': 'Logged out successfully'})
    else:
        response = make_response(redirect(url_for('views.index')))

    response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'
    return response

        
@views.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # If the user is already logged in, redirect them to the dashboard
    if current_user.is_authenticated:
        print("User is already authenticated, redirecting to notice.")
        return render_template('already_logged_in.html')

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

@views.route('/user-info', methods=['GET'])
@login_required
def get_user_info():
    return jsonify({"email": current_user.email})

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
