## [0.6.8] - 2025-10-11

### Added
- Inline category edits now persist through a dedicated `transaction_category_override` table so one-off manual tags stay put while rules continue to run. A dropdown of existing tags appears as you type for quick selection.

### Changed
- Transactions always display a category badge: rule matches show in color, manual overrides stay green, and default rows fall back to Plaid’s category string.
- Removed redundant custom category columns from the model and simplified rule application to rely solely on `custom_category_id` plus optional overrides.

### Fixed
- `ensure_category_schema` now creates the override table on the fly, preventing 1146 errors when older databases are upgraded lazily.

## [0.6.7] - 2025-10-11

### Changed
- Moved the transactions search, reset, sync, and connect controls into the top navbar so they stay visible while scrolling.
- Simplified the transactions pane layout to keep the summary inline and restore the table header’s default positioning (no sticky offset).
- Darkened institution cards to match the sidebar header and ensured the table header reflects the latest viewport height without gaps.

### Fixed
- Removed gaps introduced by previous sticky header attempts so the transactions table renders flush beneath the summary.

## [0.6.6] - 2025-10-11

### Changed
- Accounts pane now scrolls independently, gains a calm green theme, and can be resized so account selection stays visible alongside transactions.
- Added a global “All Accounts” toggle with indeterminate feedback plus streamlined institution rows that keep reconnect within reach.
- Transactions table page-loads results with a “Load more” control and reports how many rows are loaded versus the Plaid totals.

## [0.6.5] - 2025-02-23

### Added
- Persist Plaid activity in a dedicated `transactions` table with a new Alembic migration, capturing per-account details alongside cursor tracking on credentials.
- `/api/transactions` endpoint exposing the user’s stored transactions for the new dashboard view.

### Changed
- Dashboard sidebar now presents connected institutions as an accordion with account-level checkboxes, keeping selections in sync with the main table.
- Institution rows now include a master checkbox to toggle all related accounts and an inline “Reconnect” action.
- Main dashboard pane replaced with a sortable, filterable transactions grid plus one-click Plaid sync that refreshes data without leaving the page.
- Transactions sync pipeline writes directly to the database via `/api/transactions/sync`, returning per-institution summaries and surfacing Plaid login requirements.
- Vue/Plaid front-end logic refreshed to hydrate data after new connections or refreshes instead of forcing a full page reload.

### Removed
- Account enable/disable switches from the dashboard; table visibility is now controlled exclusively through the accordion selection.

## [0.6.4] - 2025-10-10

### Changed
- Reworked authentication to rely exclusively on Flask-Login session cookies: removed Excel add-in token handling, converted all dashboard/API routes to `login_required`, and simplified login/logout responses.
- Adjusted configuration and CORS settings so session cookies function in local dev while keeping environment-specific behaviour (`SESSION_COOKIE_*` overrides, trimmed allow-list headers).
- Updated profile management to drop token fields and rely on password resets via the new `User.set_password` helper.

### Removed
- Token regeneration UI and related endpoints, along with model helpers for generating/validating application tokens.

### Fixed
- Ensured the login form always renders email/password inputs explicitly, avoiding browser autofill conflicts with hidden fields.

## [0.6.1] - 2025-02-01

### Fixed
- **Plaid Token Exchange Parsing in `/handle_token_and_accounts`:**  
  - Corrected the extraction of the `item_id` from Plaid’s public token exchange response when adding new accounts.  
  - The code now retrieves `item_id` directly from the top-level of the response (i.e., using `exchange_response['item_id']`) instead of attempting to access a nested `item` attribute.  
  - This fix resolves the error encountered during the creation of new bank connections.

## [0.6] - 2024-12-30

### Added
- **`item_id` field** in the `Credential` model:  
  - This field stores the unique Plaid `item_id` associated with each financial institution connection.  
  - It allows the backend to correctly identify and handle institutions when Plaid sends webhooks or when existing connections are refreshed.
- **Plaid webhooks functionality** in the backend:  
  - **`/handle_token_and_accounts`** (POST) endpoint:  
    - Uses the new `item_id` to refresh or set up a webhook for an existing institution connection.  
    - Saves the `item_id` from the Plaid response into the corresponding `Credential` record.  
  - **`/plaid_webhook`** (POST) endpoint:  
    - Receives and processes Plaid webhook events.  
    - Sets `requires_update = True` on the relevant `Credential` if an `ITEM_LOGIN_REQUIRED` or `NEW_ACCOUNTS_AVAILABLE` event is triggered.  
    - Inserts a record in the `PlaidTransaction` table to log the webhook event and the corresponding institution connection details.  

### Changed
- **`core_views`** logic enhanced to handle incoming Plaid webhooks.  
- Existing connection refresh flow updated to incorporate the new `item_id`.

No other changes were introduced in this version.

## [0.5.1] - 2024-11-14

### Added
- Added account ID to Transaction Identifier to avoid deletion of incorrect transactions.

### Fixed
- Fixed issue with deletion of existing transactions.
- Fixed error when adding comments.

### Removed
- Removed width and height from comments.

## [0.5.0] - 2024-11-04

### Added
- Updated formulas and tables in the template.
- Added support for notes and help notes in the template.

## [0.4.0] - 2024-08-05

### Fixed
- Completed JSON template to fix issues with the add-in on Excel 265 online.
- Fixed issue with pivot table refreshing.

## [0.3.1] - 2024-06-30

### Added
- Detailed instructions and configuration for generating a trusted Certificate Authority (CA) and signing a server certificate using OpenSSL.
- Integration of Subject Alternative Names (SAN) in the certificate generation process to ensure compatibility with modern browsers.
- Updated Flask application configuration to utilize the newly generated server certificate and key files for HTTPS.
- Steps for importing the CA certificate into the Trusted Root Certification Authorities store on Windows for development environments.

### Improved
- Enhanced security for the development environment by ensuring the self-signed certificates are recognized as valid by the browser.
- Comprehensive guide included to aid developers in setting up a secure local development environment with SSL/TLS encryption.
- Enhanced manifest.xml


## [0.3.0] - 2024-06-17

### Added
- Initial beta release of the Excel Add-In.
- Included an Excel template in the assets subdirectory under the add-in `dist` folder for managing Accounts and Transactions table and elements in the dashboard.

### Important Notes
- Formulas in the Transactions table must be added to the Formulas table in the "Conf" sheet.
- Named ranges need to be updated from the Office.js API.
- Any PivotTable needs to be recreated via command.

### Script Breakdown
- **Console Log:** Indicates that the dashboard script has been loaded successfully.
- **Show Toast Function:** Displays a temporary message to the user with different types (info, success, warning, error).
- **Sync Transactions Button:** Attaches a click event handler to the sync transactions button to initiate the sync process.
- **Office onReady Event:** Ensures that the script waits for the Office context to be ready before attaching event handlers and performing other operations.
- **Get Cursors Function:** Retrieves cursor values from the Accounts table for syncing transactions.
- **Create Card Function:** Generates a card element to display messages about success or error transactions.
- **Sync Transactions Function:** Handles the entire process of syncing transactions, including authentication, data retrieval, and processing.
- **Process Transaction Data Function:** Processes the retrieved transaction data and updates the relevant Excel tables.
- **Import Template Sheets Function:** Ensures that the necessary template sheets are imported into the workbook if they do not already exist.
- **Insert Transaction Data Function:** Inserts transaction data into the Accounts and Transactions tables in the Excel workbook.
- **Apply Formulas to Transactions Function:** Applies formulas from the Formulas table to the Transactions table.
- **Update Named Ranges Function:** Updates named ranges in the workbook based on the configuration in the Names table.
- **Recreate Pivot Table Function:** Recreates the PivotTable named "Summary" to reflect the latest data and configurations.
- **Create Error Card Function:** Creates and displays an error card for any issues encountered during the transaction sync process.
- **Create Success Card Function:** Creates and displays a success card for successful transactions.


## [0.2.0] - 2024-03-26 
### Added
- Added Excel Add-In code.

### Changed
- Updated /sync API to include number of transactions and type of refresh
- Updated /sync API to record an audit entry with response from Plaid in every refresh

## [0.1.4] - 2024-04-02

### Added
- Excel Add-In code.

## [0.1.3] - 2024-04-01

### Added
- Integrated Bitwarden Secrets Manager (BWS) for secure management of sensitive configuration information, including database passwords, Plaid credentials, and mail server settings.
- Implemented `get_bw_secret` function in `config.py` to dynamically fetch secrets based on secret keys from BWS, enhancing security and configuration management.
- Established two BWS service accounts: one designated for production (`ExMint-Prod`) and another for development and staging (`ExMint-Dev`). This strategy ensures appropriate separation and access control for environment-specific secrets.
- Added documentation within `config.py` detailing the purpose and usage of each function, particularly emphasizing the secure retrieval of secrets from BWS and the rationale behind using separate service accounts for different environments.

### Changed
- Replaced hard-coded sensitive information in the application configuration with dynamically retrieved secrets from BWS. This change applies to the following configuration settings:
    - Database URIs across different environments (development, staging, production).
    - Secret keys and encryption keys used for security purposes.
    - Plaid API credentials, supporting both development and production usage with environment-appropriate access.
    - Mail server configurations, including server addresses, ports, and authentication credentials.

### Security
- Enhanced application security by removing hard-coded sensitive information from the codebase. All sensitive configurations are now securely stored and managed through BWS, minimizing potential exposure and risk.
- Implemented case-insensitive search within `get_bw_secret` function to robustly match secret keys, improving the reliability of secret retrieval across varied naming conventions.

### Fixed
- Addressed potential configuration management issues by introducing a more secure, scalable, and maintainable approach to handling sensitive information through the integration of BWS.


## [0.1.2] - 2024-03-26 
### Added
- Added automatic database switching based on Git branch.

## [0.1.1] - 2024-03-26 
### Added
- Added version information to the footer of the dashboard.
- Added 'version' key to the JSON response of the /sync API endpoint for better tracking and compatibility.

### Removed
- Removed 'Support' button from the dashboard header for a cleaner user interface.
- Removed 'Help and Support' right sidebar from the dashboard to streamline user experience.

### Changed
- Updated footer styling for better readability and alignment using Bootstrap classes.
- Made 'Automatos Consulting Inc.' a clickable link in the footer, linking to the official website.

## [0.1.0] - 2024-03-27
### Added
- Initial release of exMint.
- Support for user authentication and profile management.

### Fixed
- Corrected timezone discrepancies in log entries.

### Changed
- Updated Flask framework from 1.1.2 to 1.1.3 for improved security.

Of course, Manuel. Here is the changelog entry for the recent changes.

## [0.63] - 2024-05-24
### Fixed
- Resolved a critical issue where duplicate transactions would appear in the Excel `Transactions` table if the same bank account was linked to ExMint more than once.

### Added
- A new `createTransactionFingerprint` helper function in `dashboard.js` to generate a unique identifier for transactions based on their stable properties (date, amount, name, account mask).

### Changed
- Updated the transaction processing logic in `dashboard.js` (`insertTransactionData` function) to use the new fingerprinting method, ensuring that transactions from duplicate bank connections are identified and skipped during the sync process.
