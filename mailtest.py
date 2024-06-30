from flask import Flask
from flask_mail import Mail, Message

app = Flask(__name__)

app.config['MAIL_SERVER'] = 'mail.exmint.me'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'noreply@exmint.me'
app.config['MAIL_PASSWORD'] = 'CNIr|vIk?v2ho;y6'

mail = Mail(app)

@app.route('/send_test_email')
def send_test_email():
    msg = Message('Test Email', sender=app.config['MAIL_USERNAME'], recipients=['manuelmuisca@gmail.com'])
    msg.body = 'This is a test email'
    try:
        mail.send(msg)
        return 'Email sent successfully'
    except Exception as e:
        return f'Error: {e}'

if __name__ == '__main__':
    app.run(debug=True)
