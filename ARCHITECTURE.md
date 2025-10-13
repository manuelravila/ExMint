# ExMint Architecture

This document provides an overview of the ExMint application's architecture, data strategy, and key components.

## 1. High-Level Architecture

ExMint is a web-based personal finance dashboard that allows users to connect their bank accounts, track transactions, and manage their budgets. The application follows a traditional client-server architecture:

*   **Frontend:** A single-page application (SPA) built with **Vue.js** and **Bootstrap**. The frontend is responsible for rendering the user interface, handling user interactions, and communicating with the backend via a RESTful API.
*   **Backend:** A **Flask** (Python) application that serves the frontend, handles user authentication, and provides a RESTful API for accessing and managing financial data.
*   **Database:** A **SQLite** database (for development) and a **MySQL** database (for production) are used to store user data, including account information, transactions, and budgets.
*   **Plaid Integration:** The application uses **Plaid** to securely connect to users' bank accounts and retrieve financial data.

## 2. Data Strategy

The application's data strategy is centered around the following principles:

*   **Data Security:** All sensitive user data, such as bank credentials and API keys, is encrypted and stored securely. The application uses **Bitwarden Secrets Manager** to manage secrets.
*   **Data Integrity:** The application uses a relational database to store data, which helps to ensure data integrity. The database schema is managed using **Alembic** migrations.
*   **Data Privacy:** The application only retrieves the data that is necessary to provide its services. The application does not store any personally identifiable information (PII) that is not essential for its operation.

## 3. Key Components

The application is composed of the following key components:

### Frontend (Vue.js)

*   **`dashboard.html`:** The main HTML template for the dashboard. It includes the basic layout of the page and loads the necessary CSS and JavaScript files.
*   **`vuePlaid.js`:** The main JavaScript file for the Vue.js application. It contains the Vue instance, computed properties, and methods for handling user interactions and communicating with the backend.
*   **`LineChart.js`:** A Vue component that wraps the `vue-chartjs` library to create a reusable line chart component.

### Backend (Flask)

*   **`app.py`:** The main entry point for the Flask application. It initializes the Flask app, configures the database, and registers the blueprints for the different parts of the application.
*   **`views.py`:** This file contains the main views for the application, such as the login, registration, and dashboard pages.
*   **`core_views.py`:** This file contains the API endpoints for accessing and managing financial data.
*   **`models.py`:** This file defines the database models for the application, such as the `User`, `Credential`, `Account`, and `Transaction` models.
*   **`config.py`:** This file contains the configuration for the application, such as the database URI and the Plaid API keys.

### Other Components

*   **`Alembic`:** A database migration tool for SQLAlchemy. It is used to manage changes to the database schema.
*   **`Bitwarden Secrets Manager`:** A secrets management tool that is used to store and manage sensitive information, such as API keys and database credentials.
*   **`Plaid`:** A financial data aggregation service that is used to connect to users' bank accounts and retrieve financial data.

## 4. Data Flow

The following is a high-level overview of the data flow in the application:

1.  The user logs in to the application.
2.  The frontend makes a request to the backend to retrieve the user's financial data.
3.  The backend retrieves the data from the database and from Plaid.
4.  The backend sends the data to the frontend in JSON format.
5.  The frontend uses the data to render the dashboard, including the transaction list, account balances, and cash flow chart.
