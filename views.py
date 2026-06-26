# views.py
from flask import current_app, render_template, redirect, url_for, flash, request, jsonify, Blueprint, session, make_response
from flask_login import login_user, current_user, logout_user, login_required
from flask_wtf import FlaskForm
from extensions import mail
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from forms import LoginForm, RegistrationForm, ProfileForm
from models import (User, db, Credential, Account, Transaction,
                    TransactionCategoryOverride, Budget, CustomCategory, CategoryRule,
                    get_app_setting, set_app_setting)
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from datetime import datetime
from functools import wraps

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
        current_app.logger.info("Activation email sent to %s", email)
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

    if get_app_setting('registration_open', 'true') != 'true':
        return render_template('register.html', title='Register',
                               suffix=current_app.config.get('SUFFIX', ''),
                               form=None, registration_closed=True)

    form = RegistrationForm()
    if form.validate_on_submit():
        email = form.email.data
        hashed_password = generate_password_hash(form.password.data)

        user = User(email=email, password_hash=hashed_password, status='PendingApproval')
        db.session.add(user)
        db.session.commit()

        send_admin_registration_notification(email)

        flash("Registration request received! You'll be notified by email once your account is approved.", "info")
        return redirect(url_for('views.login'))

    return render_template('register.html', title='Register',
                           suffix=current_app.config.get('SUFFIX', ''),
                           form=form, registration_closed=False)


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
        return handle_authenticated_user()

    if request.method == 'POST':
        return handle_login_request()

    form = LoginForm()
    welcome_message = get_app_setting('login_welcome_message', '')
    return render_template('index.html', form=form, welcome_message=welcome_message)


def handle_login_request():
    # Distinguish between JSON and Form submissions
    if request.is_json:
        data = request.get_json() or {}
        username_or_email = data.get('login')
        password = data.get('password')
    else:
        username_or_email = request.form.get('login')
        password = request.form.get('password')

    # Authenticate the user
    if username_or_email and password:
        user = User.query.filter(User.email == username_or_email).first()
        if user and check_password_hash(user.password_hash, password):
            # Check if user has activated their account
            if user.status == 'PendingApproval':
                error_message = 'Your account is pending approval. You will be notified by email when it is approved.'
                return handle_unsuccessful_login(error_message)
            if user.status == 'Rejected':
                error_message = 'Your registration was not approved. Please contact the administrator.'
                return handle_unsuccessful_login(error_message)
            if user.status != 'Active':
                error_message = 'Account not activated. Please check your email for the activation link.'
                return handle_unsuccessful_login(error_message)
            
            login_user(user, remember=False)
            reset_new_transaction_flags(user)
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


def reset_new_transaction_flags(user):
    if not user or not user.id:
        return
    now = datetime.utcnow()
    try:
        updated = Transaction.query.filter(
            Transaction.user_id == user.id,
            Transaction.is_new.is_(True)
        ).update({
            Transaction.is_new: False,
            Transaction.seen_by_user: True,
            Transaction.last_seen_by_user: now
        }, synchronize_session=False)
        if updated:
            db.session.commit()
    except Exception as exc:
        current_app.logger.warning('Failed to reset new transaction flags for user %s: %s', user.id, exc)
        db.session.rollback()


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
    # Only update transactions that haven't been marked as seen yet —
    # avoids a full-table write when most rows are already up to date.
    now = datetime.utcnow()
    Transaction.query.filter(
        Transaction.user_id == current_user.id,
        db.or_(Transaction.seen_by_user == False, Transaction.is_new == True)
    ).update({
        Transaction.seen_by_user: True,
        Transaction.is_new: False,
        Transaction.last_seen_by_user: now
    }, synchronize_session=False)
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
    if current_user.is_authenticated:
        return render_template('already_logged_in.html')

    if request.method == 'POST':
        email = request.form.get('email')

        user = User.query.filter_by(email=email).first()
        if user:
            # Generate a secure token
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = serializer.dumps(email, salt='email-reset-salt')

            reset_url = url_for('views.reset_password_token', token=token, _external=True)
            html_content = render_template('password_reset_email.html', reset_url=reset_url, suffix=current_app.config['SUFFIX'])
            msg = Message('Password Reset Request',
                          sender=current_app.config['MAIL_USERNAME'],
                          recipients=[email])
            msg.html = html_content

            try:
                mail.send(msg)
                current_app.logger.info("Password reset email sent to: %s", email)
            except Exception as e:
                current_app.logger.error("Failed to send password reset email to %s: %s", email, e)

        # Always render the same page to prevent user enumeration
        return render_template('password_reset_sent.html', suffix=current_app.config['SUFFIX'])

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
@login_required
def enable_account(account_id):
    account = Account.query.join(Credential).filter(
        Account.id == account_id,
        Credential.user_id == current_user.id
    ).first()
    if account:
        account.is_enabled = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'Account enabled.'})
    return jsonify({'success': False, 'message': 'Account not found.'}), 404

@views.route('/api/accounts/disable/<int:account_id>', methods=['POST'])
@login_required
def disable_account(account_id):
    account = Account.query.join(Credential).filter(
        Account.id == account_id,
        Credential.user_id == current_user.id
    ).first()
    if account:
        account.is_enabled = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Account disabled.'})
    return jsonify({'success': False, 'message': 'Account not found.'}), 404


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('views.login', next=request.url))
        if current_user.role != 'Admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('views.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def _delete_user_data(user_id):
    """Delete all data for a user in FK-safe order. Does NOT delete the User row itself."""
    # 1. TransactionCategoryOverride (FK to transactions.id and custom_categories.id)
    TransactionCategoryOverride.query.filter(
        TransactionCategoryOverride.transaction_id.in_(
            db.session.query(Transaction.id).filter_by(user_id=user_id)
        )
    ).delete(synchronize_session=False)
    # 2. Clear split-child parent references to avoid self-referential FK constraint
    Transaction.query.filter_by(user_id=user_id).update(
        {'parent_transaction_id': None}, synchronize_session=False
    )
    # 3. Transactions (FK to account.id, credential.id, custom_categories.id)
    Transaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    # 4. Accounts (FK to credential.id)
    Account.query.filter(
        Account.credential_id.in_(
            db.session.query(Credential.id).filter_by(user_id=user_id)
        )
    ).delete(synchronize_session=False)
    # 5. Credentials
    Credential.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    # 6. Budgets
    Budget.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    # 7. Category rules (FK to custom_categories.id)
    CategoryRule.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    # 8. Custom categories
    CustomCategory.query.filter_by(user_id=user_id).delete(synchronize_session=False)


def send_admin_registration_notification(email):
    """Send admin an email with one-click approve/reject links for a new registration."""
    admin_email = current_app.config.get('ADMIN_EMAIL', '')
    if not admin_email:
        current_app.logger.warning('ADMIN_EMAIL not set — registration notification skipped for %s', email)
        return
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    approve_token = serializer.dumps(email, salt='admin-approve-salt')
    reject_token = serializer.dumps(email, salt='admin-reject-salt')
    approve_url = url_for('views.admin_approve_via_email', token=approve_token, _external=True)
    reject_url = url_for('views.admin_reject_via_email', token=reject_token, _external=True)
    suffix = current_app.config.get('SUFFIX', '')
    html_content = render_template('email_admin_registration.html',
                                   email=email,
                                   approve_url=approve_url,
                                   reject_url=reject_url,
                                   suffix=suffix)
    msg = Message('New ExMint Registration Request',
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[admin_email])
    msg.html = html_content
    try:
        mail.send(msg)
        current_app.logger.info('Admin registration notification sent for %s', email)
    except Exception as e:
        current_app.logger.error('Failed to send admin registration notification: %s', e)


def send_user_approved_email(email):
    suffix = current_app.config.get('SUFFIX', '')
    login_url = url_for('views.login', _external=True)
    html_content = render_template('email_user_approved.html', login_url=login_url, suffix=suffix)
    msg = Message('Your ExMint Account Has Been Approved',
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[email])
    msg.html = html_content
    try:
        mail.send(msg)
    except Exception as e:
        current_app.logger.error('Failed to send approval email to %s: %s', email, e)


def send_user_rejected_email(email):
    suffix = current_app.config.get('SUFFIX', '')
    html_content = render_template('email_user_rejected.html', suffix=suffix)
    msg = Message('Your ExMint Registration Request',
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[email])
    msg.html = html_content
    try:
        mail.send(msg)
    except Exception as e:
        current_app.logger.error('Failed to send rejection email to %s: %s', email, e)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@views.route('/admin')
@admin_required
def admin_panel():
    csrf_form = FlaskForm()
    pending_users = User.query.filter_by(status='PendingApproval').order_by(User.id.desc()).all()
    all_users = User.query.order_by(User.id.desc()).all()
    registration_open = get_app_setting('registration_open', 'true') == 'true'
    welcome_message = get_app_setting('login_welcome_message', '')
    return render_template('admin.html',
                           csrf_form=csrf_form,
                           pending_users=pending_users,
                           all_users=all_users,
                           registration_open=registration_open,
                           welcome_message=welcome_message)


@views.route('/admin/welcome-message', methods=['POST'])
@admin_required
def set_welcome_message():
    csrf_form = FlaskForm()
    if not csrf_form.validate_on_submit():
        flash('Invalid request.', 'danger')
        return redirect(url_for('views.admin_panel'))
    message = request.form.get('welcome_message', '').strip()
    set_app_setting('login_welcome_message', message)
    flash('Welcome message updated.' if message else 'Welcome message cleared.', 'success')
    return redirect(url_for('views.admin_panel'))


@views.route('/admin/toggle-registration', methods=['POST'])
@admin_required
def toggle_registration():
    current_val = get_app_setting('registration_open', 'true')
    new_val = 'false' if current_val == 'true' else 'true'
    set_app_setting('registration_open', new_val)
    state = 'opened' if new_val == 'true' else 'closed'
    flash(f'Registration has been {state}.', 'success')
    return redirect(url_for('views.admin_panel'))


@views.route('/admin/users/<int:user_id>/approve', methods=['POST'])
@admin_required
def admin_approve_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.status != 'PendingApproval':
        flash('User not found or not pending approval.', 'warning')
        return redirect(url_for('views.admin_panel'))
    user.status = 'Active'
    db.session.commit()
    send_user_approved_email(user.email)
    flash(f'{user.email} approved.', 'success')
    return redirect(url_for('views.admin_panel'))


@views.route('/admin/users/<int:user_id>/reject', methods=['POST'])
@admin_required
def admin_reject_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.status != 'PendingApproval':
        flash('User not found or not pending approval.', 'warning')
        return redirect(url_for('views.admin_panel'))
    user.status = 'Rejected'
    db.session.commit()
    send_user_rejected_email(user.email)
    flash(f'{user.email} rejected.', 'success')
    return redirect(url_for('views.admin_panel'))


@views.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'warning')
        return redirect(url_for('views.admin_panel'))
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('views.admin_panel'))

    # Revoke active Plaid connections before wiping data
    from core_views import deactivate_plaid_token
    active_creds = Credential.query.filter_by(user_id=user.id, status='Active').all()
    for cred in active_creds:
        if cred.access_token:
            deactivate_plaid_token(cred.access_token)

    _delete_user_data(user.id)
    deleted_email = user.email
    db.session.delete(user)
    db.session.commit()
    flash(f'User {deleted_email} and all their data have been deleted.', 'success')
    return redirect(url_for('views.admin_panel'))


@views.route('/admin/approve/<token>')
def admin_approve_via_email(token):
    """One-click approve from email link — no login required."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='admin-approve-salt', max_age=7 * 86400)
    except (SignatureExpired, BadSignature):
        flash('This approval link is invalid or has expired.', 'danger')
        return redirect(url_for('views.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('views.login'))
    if user.status != 'PendingApproval':
        flash(f'{email} has already been processed (status: {user.status}).', 'info')
        return redirect(url_for('views.login'))

    user.status = 'Active'
    db.session.commit()
    send_user_approved_email(user.email)
    flash(f'{email} has been approved and notified.', 'success')
    return redirect(url_for('views.login'))


@views.route('/admin/reject/<token>')
def admin_reject_via_email(token):
    """One-click reject from email link — no login required."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='admin-reject-salt', max_age=7 * 86400)
    except (SignatureExpired, BadSignature):
        flash('This rejection link is invalid or has expired.', 'danger')
        return redirect(url_for('views.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('views.login'))
    if user.status != 'PendingApproval':
        flash(f'{email} has already been processed (status: {user.status}).', 'info')
        return redirect(url_for('views.login'))

    user.status = 'Rejected'
    db.session.commit()
    send_user_rejected_email(user.email)
    flash(f'{email} has been rejected and notified.', 'success')
    return redirect(url_for('views.login'))
