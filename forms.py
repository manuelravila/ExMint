#forms.py
from flask_wtf import FlaskForm
from flask_login import current_user
from wtforms import StringField, PasswordField, SubmitField, validators
from models import User

class LoginForm(FlaskForm):
    login = StringField('Email', validators=[validators.DataRequired()])
    password = PasswordField('Password', validators=[validators.DataRequired()])
    submit = SubmitField('Log In')

class RegistrationForm(FlaskForm):
    # Removed: username = StringField('Username', validators=[validators.DataRequired(), validators.Length(min=2, max=20)])
    email = StringField('Email', validators=[validators.DataRequired(), validators.Email()])
    password = PasswordField('Password', validators=[validators.DataRequired()])
    confirm_password = PasswordField('Repeat Password', validators=[validators.DataRequired(), validators.EqualTo('password')])
    submit = SubmitField('Register')

class ProfileForm(FlaskForm):
    # Removed: username = StringField('Username', validators=[validators.DataRequired(), validators.Length(min=2, max=20)])
    email = StringField('Email', validators=[validators.DataRequired(), validators.Email()])
    password = PasswordField('Password', validators=[validators.Optional()])
    confirm_password = PasswordField('Confirm Password', validators=[validators.EqualTo('password', message='Passwords must match')])
    submit = SubmitField('Update')

    # Token management elements
    token = StringField('Token', render_kw={'readonly': True})
    regenerate_token = SubmitField('Regenerate Token')

    def __init__(self, *args, **kwargs):
        self.is_registration = kwargs.pop('is_registration', False)
        super(ProfileForm, self).__init__(*args, **kwargs)
        if self.is_registration:
            self.password.validators = [validators.DataRequired()]
            self.confirm_password.validators.append(validators.DataRequired())
