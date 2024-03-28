# ExMint: Personal Financial Dashboard

ExMint is an advanced, feature-rich personal financial dashboard designed to provide users with a comprehensive view of their financial situation. Integrating with the Plaid API, it offers seamless connectivity with various financial institutions, allowing users to monitor their bank accounts, track transactions, and manage financial connections—all in one intuitive interface.

## Features

- **Plaid Integration:** Securely connect with multiple financial institutions to fetch real-time financial data.
- **Dashboard Overview:** Get a quick snapshot of all connected bank accounts and recent transactions at a glance.
- **Account Management:** Add or remove bank connections with ease. All bank credentials are encrypted for enhanced security.
- **Transaction History:** View detailed transaction histories for each connected account. Filter and search functionalities make it easy to find specific transactions.
- **Responsive Design:** A clean, user-friendly interface that adapts to various screen sizes, ensuring a seamless experience on both desktop and mobile devices.
- **Vue.js Powered Frontend:** Dynamic and responsive frontend built with Vue.js for an interactive user experience.
- **Flask Backend:** Robust backend developed with Flask, ensuring efficient handling of requests, data processing, and API integrations.
- **Secure User Authentication:** Secure login mechanism with options to update profile details and regenerate tokens.
- **Real-Time Data Syncing:** Synchronize data in real-time with the financial institutions to keep the financial information up-to-date.

## Tech Stack

- **Frontend:** Vue.js, JavaScript, HTML5, CSS3, Bootstrap
- **Backend:** Flask (Python), SQLAlchemy for ORM
- **Database:** PostgreSQL
- **APIs:** Plaid API for financial data integration
- **Other Technologies:** Flask-Migrate for database migrations, Flask-Login for handling user authentication

## Installation and Setup

Instructions for setting up ExMint on a local development environment are as follows:

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/<your-username>/ExMint.git
   cd ExMint
  
2. **Install Dependencies:**
```bash
  Copy code
  pip install -r requirements.txt
```
Ensure that HashiCorp Vault Amd64 executable is present in a location in PATH on Windows (https://developer.hashicorp.com/vault/install#windows) or 

3. **Environment Configuration:**
Set up your .env file with the necessary environment variables including PLAID_CLIENT_ID, PLAID_SECRET, and DATABASE_URL.
Initialize the Database:

```bash
Copy code
flask db upgrade
```
4. **Run the Application:**

```bash
Copy code
flask run
```
5. **Contributions**
Contributions to ExMint are welcome! Whether it's bug fixes, feature suggestions, or improvements to documentation, your input is valued. Please feel free to submit issues and pull requests.

6. **License**
ExMint is released under the MIT License.
