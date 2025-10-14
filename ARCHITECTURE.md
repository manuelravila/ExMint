# ExMint Architecture

This document provides an overview of the ExMint application's architecture, data strategy, and key components.

## 1. High-Level Architecture

ExMint is a web-based personal finance dashboard that allows users to connect their bank accounts, track transactions, and manage their budgets. The application follows a traditional client-server architecture:

- **Frontend:** A single-page application (SPA) built with **Vue.js** and **Bootstrap**. The frontend is responsible for rendering the user interface, handling user interactions, and communicating with the backend via a RESTful API.
- **Backend:** A **Flask** (Python) application that serves the frontend, handles user authentication, and provides a RESTful API for accessing and managing financial data.
- **Database:** A **SQLite** database (for development) and a **MySQL** database (for production) are used to store user data, including account information, transactions, and budgets.
- **Plaid Integration:** The application uses **Plaid** to securely connect to users' bank accounts and retrieve financial data.

## 2. Data Strategy

The application's data strategy is centered around the following principles:

- **Data Security:** All sensitive user data, such as bank credentials and API keys, is encrypted and stored securely. The application uses **Bitwarden Secrets Manager** to manage secrets.
- **Data Integrity:** The application uses a relational database to store data, which helps to ensure data integrity. The database schema is managed using **Alembic** migrations.
- **Data Privacy:** The application only retrieves the data that is necessary to provide its services. The application does not store any personally identifiable information (PII) that is not essential for its operation.

## 3. Key Components

The application is composed of the following key components:

### Frontend (Vue.js)

- **`dashboard.html`:** The main HTML template for the dashboard. It includes the basic layout of the page and loads the necessary CSS and JavaScript files.
- **`vuePlaid.js`:** The main JavaScript file for the Vue.js application. It contains the Vue instance, computed properties, and methods for handling user interactions and communicating with the backend.
- **`LineChart.js`:** A Vue component that wraps the `vue-chartjs` library to create a reusable line chart component.

### Backend (Flask)

- **`app.py`:** The main entry point for the Flask application. It initializes the Flask app, configures the database, and registers the blueprints for the different parts of the application.
- **`views.py`:** This file contains the main views for the application, such as the login, registration, and dashboard pages.
- **`core_views.py`:** This file contains the API endpoints for accessing and managing financial data.
- **`models.py`:** This file defines the database models for the application, such as the `User`, `Credential`, `Account`, and `Transaction` models.
- **`config.py`:** This file contains the configuration for the application, such as the database URI and the Plaid API keys.

### Other Components

- **`Alembic`:** A database migration tool for SQLAlchemy. It is used to manage changes to the database schema.
- **`Bitwarden Secrets Manager`:** A secrets management tool that is used to store and manage sensitive information, such as API keys and database credentials.
- **`Plaid`:** A financial data aggregation service that is used to connect to users' bank accounts and retrieve financial data.

## 4. Data Flow

The application features two primary data flow models: a user-initiated (synchronous) flow and a webhook-driven (asynchronous) flow.

### User-Initiated Data Flow

1.  The user logs in and interacts with the dashboard (e.g., clicks the "Sync" button).
2.  The frontend makes an API request to a backend endpoint (e.g., `/api/transactions/sync`).
3.  The backend immediately communicates with Plaid to fetch the latest data for all of the user's connected institutions.
4.  The backend processes the response from Plaid, persists the new or updated transactions to the database, and sends a summary back to the frontend.
5.  The frontend refreshes the view to display the latest information. Transactions fetched this way are **not** marked as "New".

### Asynchronous Data Flow (Webhooks)

This flow allows for background data updates without direct user interaction.

1.  Plaid sends a webhook notification (e.g., `SYNC_UPDATES_AVAILABLE`) to a dedicated endpoint on the Flask backend (`/api/plaid/webhook`).
2.  The backend receives the webhook, identifies the relevant user credential via the `item_id` in the payload, and initiates a transaction sync for that specific credential.
3.  During this process, newly added transactions are flagged in the database with `is_new = True`.
4.  The next time the user logs in or refreshes their dashboard, the frontend fetches all transactions.
5.  Transactions flagged as `is_new` are displayed with a "New" tag, alerting the user to recent, unseen activity. Clicking the transaction removes the tag.
