## [1.3.9] - 2026-04-16

### Added

- **Automatic redirect on session expiry**: when the Flask session expires, any API call from the dashboard now receives a JSON 401 response (via a custom `unauthorized_handler`) instead of an HTML redirect that the SPA couldn't interpret. A global `fetch` interceptor in `vuePlaid.js` catches every 401 and immediately navigates the page to `/login?session_expired=1`, so the user sees the login screen rather than a broken dashboard.
- **Session-expired toast on login page**: when redirected due to session expiry, the login page now shows a dismissible Bootstrap Toast ("Your session has expired. Please log in again.") anchored to the top-right corner, replacing the previously unformatted flash alert that rendered at the top of the page.

---

## [1.3.8] - 2026-04-16

### Changed

- **Budget category field replaced with native `<select>`**: the custom typeahead dropdown was unreliable inside a `<table>` because absolutely-positioned elements are clipped by table layout contexts regardless of overflow settings. New budget rows now use a native `<select>` populated with custom categories that don't already have a budget. Saved budget rows show the category as plain text (category is fixed after saving).

---

## [1.3.7] - 2026-04-16

### Fixed

- **Budget category dropdown empty**: custom categories were never fetched when navigating directly to the Budgets pane. `setActivePane('budgets')` now loads custom categories (suppressed loader) alongside budgets, so the dropdown is always populated.

---

## [1.3.6] - 2026-04-16

### Fixed

- **Budget category dropdown clipped**: the dropdown was rendered but immediately hidden by `overflow: hidden` on `.budgets-table table`. The table now uses `overflow: visible`, and the `.budgets-table` wrapper overrides Bootstrap's `table-responsive` to keep `overflow-y: visible`.
- **New budget row discarded when clicking Amount field**: `onBudgetCategoryBlur` was calling `discardBudgetRowIfEmpty`, which removed any new row whose amount was still 0 — i.e. always, before the user had a chance to fill it in. The auto-discard is removed from the blur handler entirely.
- **New budget row discarded when Amount field blurred**: same issue via `@blur="discardBudgetRowIfEmpty"` on the amount input; removed.
- **Create/Cancel buttons on new budget rows**: the save/delete icons are now labelled "Create" and "Cancel" for unsaved rows, making the form intent explicit.

---

## [1.3.5] - 2026-04-16

### Added

- **Budget category dropdown**: the Category field when adding a new budget now shows a dropdown of all available custom categories. Categories that already have a budget are excluded, enforcing the one-budget-per-category constraint. The full list appears on focus and filters as you type; the field is locked (disabled) on saved budget rows so the category cannot be accidentally changed.

---

## [1.3.4] - 2026-04-16

### Fixed

- **Recurring duplicates after deduplication**: after using the deduplication tool to remove a duplicate transaction, a subsequent Plaid sync could revive it when Plaid sent a `modified` update for that same `plaid_transaction_id`. `_persist_transactions_from_payload` now skips any transaction whose `last_action` is `maintenance_dedup` or `maintenance_dedup_cascade`, so dedup removals are permanent.
- **Fallback account query not scoped to user**: in `_persist_transactions_from_payload`, when a transaction's Plaid account ID was not in the local account map, the fallback query looked up accounts globally (no user filter). The query now joins through `Credential` and filters by `user_id`, preventing cross-user account matches.

---

## [1.3.3] - 2026-04-15

### Added

- **Bulk category assign**: select multiple transactions using the new per-row checkboxes (with select-all for the current page) and assign an existing or new custom category in one action. The bulk controls appear in the sticky navbar when any rows are selected, replacing the search bar to remain accessible while scrolling. Selected rows are highlighted in blue.

### Fixed

- **Reconnect button persists after successful re-authentication**: after completing Plaid's update-mode flow, the "Reconnect" button could remain visible even though the credential was valid and syncing correctly. A successful `transactions_sync` call now clears the `requires_update` flag directly, covering both manual syncs and webhook-triggered syncs.

---

## [1.3.2] - 2026-03-29

### Added

- **Login welcome message**: admins can set a short message (e.g. test credentials) that appears as an info box on the login page. Managed from the Admin Panel; leaving it blank hides the box. Stored in the existing `app_settings` table — no migration needed.

### Fixed

- **Admin email not sent on registration**: `ADMIN_EMAIL` was missing from `.env.stag` on the VPS, causing registration notifications to be silently skipped. Fixed by documenting the required env var and adding it to the staging environment.
- **`start.sh` broke Docker deploy**: the 1.3.1 fix for dev (`venv/bin/python`) used a host-only path that doesn't exist inside Docker containers. `start.sh` now auto-detects whether the venv is present and falls back to system `python`/`gunicorn` when running in Docker.
- **Committed merge conflict markers**: the `stag` merge commit accidentally committed raw conflict markers into 13 files instead of resolving them. All files have been corrected to their 1.3.1 HEAD versions.

## [1.3.1] - 2026-03-29

### Fixed

- **Plaid link token crash**: `PLAID_WEBHOOK_URL` being `None` (unset) caused a `TypeError` in the Plaid SDK when creating a link token. The webhook field is now only included in the request when the env var is configured.
- **Slow logout**: logout was updating `seen_by_user`, `is_new`, and `last_seen_by_user` on every transaction unconditionally. It now only updates rows where those flags actually need changing, making logout near-instant when transactions are already marked as seen.
- **`flask db upgrade` permission denied in dev**: `start.sh` was calling the venv entry-point scripts (`flask`, `gunicorn`) which lacked execute permission in the dev environment. Replaced with explicit `venv/bin/python -m flask` and `venv/bin/gunicorn` invocations.
- **Migration failure on reserved word**: `INSERT INTO app_settings (key, value)` failed on MySQL because `key` is a reserved word. Fixed by backtick-quoting the column in raw SQL and made the migration idempotent to handle partial previous runs.
- **Missing "ExMint: DB Upgrade" task**: `launch.json` referenced this VS Code task for the Prod config but it was never defined in `tasks.json`. Added the missing task.
- **No link to Admin Panel**: Admin Panel was accessible by URL but had no entry point in the UI. Added it to the My Account dropdown, visible only to users with `role='Admin'`.

## [1.3.0] - 2026-03-29

### Added

- **Admin panel** (`/admin`): accessible to users with `role='Admin'`. Provides a registration open/closed toggle, a pending-approval queue with one-click approve/reject, and a full user list with delete capability (Plaid connections are revoked before deletion).
- **Registration approval workflow**: new registrations land in `PendingApproval` status. Admin receives an email with one-click approve/reject links (valid 7 days). Users are notified by email on approval or rejection. The workflow applies to all environments.
- **Registration toggle**: admin can open or close registration from the admin panel at any time. The "Create an account" link is hidden in the login UI when registration is closed.
- **Test-user nightly cleanup**: `cleanup_test_user.py` revokes all Plaid connections and wipes all transaction/account/credential data for the account in `TEST_USER_EMAIL`, leaving the user row intact. Runs at 23:55 UTC via the Docker cron service.
- **Docker cron service**: new `cron` container in `docker-compose.yml` using the same app image. Configured via `crontab.docker` and `entrypoint_cron.sh`.
- New environment variables: `ADMIN_EMAIL` (required for approval emails), `TEST_USER_EMAIL` (required for nightly cleanup), `CRON_IP` (Docker network IP for cron container).

### Fixed

- **Email on STAG**: `MAIL_*` variables were not present in the staging environment, causing `get_secret("MAIL_PASSWORD")` to raise and silently swallow the error. Added `.env.stag` template with SMTP credentials pre-filled.

### Deployment notes

1. Run `flask db upgrade` — adds the `app_settings` table and seeds `registration_open = 'true'`.
2. Set your user's role to Admin (one-time, run from flask shell or direct SQL):
   ```sql
   UPDATE user SET role = 'Admin' WHERE email = 'your@email.com';
   ```
3. Add `ADMIN_EMAIL`, `TEST_USER_EMAIL`, and `CRON_IP` to `.env.stag` and `.env.main`.
4. The cron container starts automatically with the stack — no post-receive hook changes needed.

## [1.2.0] - 2026-03-28

### Added

- **Cross-account duplicate detection.** The Maintenance → Duplicate Transactions scanner now detects duplicates across different accounts, not just within the same account. This catches the supplementary-card scenario where Plaid issues a separate `plaid_transaction_id` for each card (primary and supplementary) but the underlying charge is the same. The scanner keeps the transaction on the older credential and flags the rest for removal.
- **Open-source release.** ExMint is now published under the GNU Affero General Public License v3.0. This release includes a new `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, GitHub issue and PR templates, and a GitHub Actions CI workflow (flake8 lint on push/PR to `dev`).

### Changed

- `secrets_manager.py` — Bitwarden Secrets Manager is now optional. `get_secret()` checks the plain environment variable first; BWS is only used when `BWS_ACCESS_TOKEN` is set. Self-hosters can configure ExMint with env vars alone.
- `config.py` — Hardcoded personal identifiers removed. All database credentials read from environment variables (or BWS). `SESSION_COOKIE_SECURE` and `SESSION_COOKIE_SAMESITE` are now derived from whether SSL is actually active, fixing a login redirect loop when running without TLS in local dev.
- `.env.example` added — documents every required environment variable with inline comments and generation commands for `SECRET_KEY` and `ENCRYPTION_KEY`.
- `RUNBOOK.md` — personal details (IPs, usernames, paths) replaced with generic placeholders, suitable for public distribution.

## [1.1.5] - 2026-03-28

### Fixed

- After deduplication, custom categories are now force-refreshed alongside the transaction list. Previously, category transaction counts remained stale until the next page load, and a race between the post-dedup refresh and a user-initiated category filter could leave the filter silently ignored (showing all transactions). Both requests now run in parallel via `Promise.all`.

## [1.1.4] - 2026-03-28

### Added

- **Maintenance → Duplicate Transactions** modal under the My Account menu.
  - **Download CSV Backup** — exports all transactions (including removed ones) before any cleanup.
  - **Scan for Duplicates** — previews duplicate groups (same account, date, amount, and description) with a Keep / Remove breakdown before any data is touched.
  - **Remove Duplicates** — marks duplicates as removed after explicit confirmation; the transaction list refreshes automatically.

### Changed

- Duplicate detection now includes split-parent transactions, covering two previously unhandled scenarios:
  - *One split, one not* — the split parent is always kept (preserves the user's categorisation work); the unsplit duplicate is removed.
  - *Both split* — the most-recently created split parent is kept; the older one is removed along with a **cascade removal of all its split children** so no orphaned rows remain.
- Within a duplicate group the keep-priority order is: split parent → posted (non-pending) → most-recent id (when split) / oldest id (when not split).
- The scan response now includes an `is_split` flag per transaction; the preview table shows a **Split** badge on kept split parents and a **Split+children** badge on split parents slated for removal, making the cascade impact visible before confirmation.

### Fixed

- Maintenance modal was placed outside the `#vue-app` root element, causing Vue directives (`v-if`, `v-else`, `@click`) and template interpolations (`[[ ... ]]`) to be ignored — all conditional panels rendered simultaneously and expressions showed as raw text. Modal moved inside the Vue root boundary.

## [1.1.3] - 2026-03-28

### Fixed

- **`read ECONNRESET` on browser caused by a broken SSH tunnel being silently treated as healthy.**
  The previous `is_listening()` check only verified that *something* had a socket bound on the tunnel port (a bare TCP `connect`).  On a container restart, the OS could briefly keep the port in `TIME_WAIT`, or the SSH process could still have its listen socket open while the path to the remote MySQL was broken — both cases made the health check pass, the tunnel setup was skipped, and the first DB query hung until gunicorn killed the worker, producing `ECONNRESET` in the browser.
  The check is replaced by `_tunnel_healthy()`, which connects and waits for MySQL's greeting packet (≥1 byte).  Receiving data proves the full path (local port → SSH → remote MySQL) is working end-to-end before `open_db_tunnel.py` declares success.
- The post-`ssh` readiness check is now a **retry loop** (`_wait_for_tunnel`, up to 15 s, polling every 0.5 s) instead of a single probe after a hard-coded 1-second sleep, making startup more robust on slow or loaded hosts.
- Added `ServerAliveCountMax=3` to the SSH command so the explicit keepalive behaviour (already using `ServerAliveInterval=30`) is fully specified and not left to the SSH client default.

## [1.1.2] - 2026-03-28

### Added

- **Maintenance menu** under My Account with two tools:
  - **Download Backup** — exports a full CSV of all transactions (including removed ones) for safe-keeping before any cleanup.
  - **Duplicate Transactions** — scan-then-fix workflow: Scan shows a colour-coded preview table of every duplicate group (green = keep, red = remove) without touching data; Remove Duplicates then marks the redundant rows as removed after a confirmation prompt and refreshes the transaction list automatically.
- Three new backend endpoints: `GET /api/maintenance/duplicates` (read-only scan), `POST /api/maintenance/deduplicate` (supports `?dry_run=true`), `GET /api/maintenance/backup` (full CSV download).

### Fixed

- **Duplicate transactions caused by concurrent sync race condition.** A Plaid webhook (`SYNC_UPDATES_AVAILABLE`) and a simultaneous manual Sync click could both call `_sync_credential_transactions` for the same credential, read the same cursor, and insert the same transactions before either committed. A row-level `SELECT … FOR UPDATE` lock is now acquired on the `Credential` row at the start of each sync, serialising concurrent callers on MySQL/MariaDB (production). The lock is a no-op on SQLite (development), where file-level locking already prevents this.

## [1.1.1] - 2026-03-18

### Added

- Duplicate bank connection guard: re-connecting the same bank through Plaid Link is now blocked at the backend. The check is account-aware — a second connection to the same institution is only rejected when every account Plaid returns already exists in the database as an active account, so households sharing one ExMint account can legitimately add separate connections at the same bank.
- When a duplicate connection is detected, the newly exchanged Plaid access token is immediately revoked to prevent orphaned items on the Plaid side, and the user receives a browser alert naming the institution.
- `UniqueConstraint('user_id', 'item_id')` added to the `Credential` model with a matching Alembic migration (`d4e5f6a7b8c9`) as a database-level safety net against duplicate credentials.

### Fixed

- Re-adding a previously removed bank no longer triggers the duplicate guard. When a bank is removed its credential and accounts are marked `Revoked`; upon re-connection those account rows are reactivated in-place (updating `credential_id` and `plaid_account_id`) so the full transaction history is immediately visible again without any data migration.
- Newly added bank accounts are now automatically selected after a connection completes. Previously, `fetchBanks` only retained the existing account selection and never appended brand-new account IDs, so transactions and dashboard metrics for a freshly linked institution were invisible until the user manually ticked the accounts.
- `start.sh` now delegates SSH tunnel setup to `open_db_tunnel.py` instead of running a raw `ssh` command, aligning the dev startup script with the dedicated tunnel utility.

## [1.1.0] - 2026-02-25

### Fixed

- Manually created categories (created by overriding a Plaid-assigned category on a parent split transaction) now appear correctly in the spending report and cash flow chart. Previously, a manual override applied to the parent of a split transaction had no visible effect on the dashboard because the accumulation loops only process split children. Split children now inherit the parent transaction's manual override when they have no custom category of their own, so the full split amount is attributed to the user-chosen category.
- Fixed phantom zero-total category entries in the spending report caused by parent split transactions. The first pass that collects distinct category labels now applies the same parent-split exclusion as the accumulation pass, so categories matched only to split-parent rows no longer create empty entries that silently disappear from the output.

## [1.0.2] - 2026-02-25

### Fixed

- Reconnect button now disappears after a successful re-authentication. The sync that runs immediately after update-mode could encounter a transient `ITEM_LOGIN_REQUIRED` response from Plaid, which set `requires_update` back to `True` before it was committed — leaving the button visible even though the user had just reconnected. The flag is now re-applied to `False` after the sync for all reconnect flows, so a transient sync error can no longer undo the re-authentication result.

## [1.0.1] - 2026-02-25

### Fixed

- Reconnect button now works again. The frontend was calling `/api/get_access_token/<id>` which was never implemented, causing a 404 that silently aborted the Plaid update-mode flow. The fix removes the extra round-trip: `createLinkToken` now accepts a `credential_id` and the backend resolves the access token internally, so the raw Plaid token is never exposed to the browser.

## [1.0.0] - 2026-02-25

### Fixed

- Transaction splitting now correctly handles Plaid amount changes: when a synced transaction has split children and its amount changes, all child transactions are deleted and the parent is restored as a normal unsplit transaction. Previously, child amounts were silently rescaled in proportion to the new total, which violated the user's explicit split breakdown.
- Category rules engine no longer overwrites or clears the categories of split child transactions. Previously, running auto-categorization could strip the user-assigned category from a split child if no rule matched its description. Split children are now fully exempt from rule evaluation and retain their manually assigned categories.
- Removed the internal `_rebalance_split_children` helper, which had become unreachable and embodied the incorrect proportional-rescaling behavior described above.

## [0.9.3] - 2025-10-22

### Changed
- Category creation confirmation now only appears for exact matches with an Automatic category, not for substrings.
- Renamed "Plaid category" to "Automatic category" in all user-facing messages for better clarity.

### Fixed
- Fixed an infinite loop bug that occurred when confirming the creation of a new category with the same name as an existing Automatic category.

## [0.9.2] - 2025-10-21

### Added

- CSV and Excel exports that honor the current transactions filters, plus a "Clear All" shortcut beside the filter bar for one-click resets.
- Long-press gesture on touch devices to open the transaction context menu without a mouse.
- Category rule entries link back to their custom category in the management tab for quicker edits.

### Changed

- Transaction category suggestions now only surface custom categories, enforce a three-character minimum, and sort the management table alphabetically while reusing colors when available.
- Split transactions now refresh the table immediately, hide the original row, persist user-selected categories for each child, and trigger dashboard refreshes after changes.
- Spending report totals display net monthly cash flow, rows stay left aligned, and dashboard metrics refresh right after transaction/category updates.
- Logging out or returning after a session timeout clears the "New" badge on transactions.
- Split modal category suggestion dropdown now floats above the table so every child row can access the helper list.

### Fixed

- Blocked accidental creation of custom categories that duplicate Plaid-provided labels or existing user categories.
- "Uncategorized" spending row now reflects the true signed total of uncategorized transactions.

## [0.9.1] - 2025-10-19

### Added

- Transactions table now includes quick filters for date range, custom category (or uncategorized), and amount range to narrow large ledgers in-place.
- Spending report category rows are clickable shortcuts that jump to the transactions pane with the selected category and month pre-filtered.
- Each spending month now rolls up an explicit “Uncategorized” line summarizing activity without a custom category.

### Changed

- Spending report styling aligns with the transactions table (striped rows, left-aligned columns) for easier scanning.
- Backend transactions API supports the new filters, normalizing user input and ensuring manual overrides/custom categories are respected.

### Fixed

- Dashboard spending calculations ignore fallback Plaid labels so only custom categories (plus the new uncategorized bucket) drive the report.

## [0.9.0] - 2025-10-20

### Added

- Dedicated "Edit Categories" management tab with CRUD support for custom categories and color selection.
- REST API endpoints and Alembic migration to persist custom categories separately from automation rules.
- Categories tab styling now matches dashboard tabs for a consistent look and feel.
- Added defensive error handling for custom category updates/overrides to surface friendly messages when duplicates are attempted.

### Changed

- Category rules now reference shared custom category records; colors are determined by the category instead of the rule.
- Transaction manual overrides align with custom categories so renames and color changes propagate automatically.
- Category management tables now use click-to-edit interactions, matching the transactions table for better responsiveness.

## [0.8.0] - 2025-10-16

### Removed

- Removed `PlaidTransaction` and `Subscription` models and all related functions from the application. This change reflects the move away from commercial features to a personal-use-only version of ExMint.
- Deleted associated database migration files for `PlaidTransaction` and `Subscription` to clean up the project.

### Changed

- Updated `core_views.py` to remove all references and logic related to `PlaidTransaction`.
- New minor version for new alembic count

## [0.7.1] - 2025-10-20

### Added

- The "New" tag is now exclusively applied to transactions synced via background Plaid webhooks, distinguishing them from transactions fetched during a manual sync.

### Changed

- Clicking a transaction row with a "New" tag now automatically marks it as "seen," providing a more intuitive and seamless user experience.

### Removed

- The "Mark all as seen" button has been removed from the transactions pane, as its functionality is now handled by clicking individual new transactions.

## [0.7.0] - 2025-10-13

### Fixed

- Cash Flow widget now displays a line chart instead of a bar chart.
- Fixed an issue where the chart would not render due to incorrect CDN resource links.

### Changed

- Replaced the custom bar chart with a line chart from `vue-chartjs`.

## [0.6.11] - 2025-01-07

### Added

- Dashboard overview pane with tabbed “Balances & Spending” and “Cash Flow” views, complete with collapsible summaries and category drill-downs.
- Cash flow selector to analyze trailing 12-month net totals for all spending or individual categories.

### Changed

- Balance totals automatically group accounts by type and institution with dynamic roll-ups.
- Spending report now pivots by year → month → category with quick year selection and default expansion of the latest month.
- Dashboard visuals now round figures to whole dollars for faster scanning.

### Fixed

- Resolved budget form validation to discard incomplete draft rows when focus exits without valid input.

## [0.6.10] - 2025-01-07

### Added

- Introduced Budgets dashboard pane with editable category, frequency, and amount columns plus auto-calculated 6-month averages and current-month totals.
- Added income versus expense detection with color coding, and a summary banner showing net (income - expenses).
- Provided inline category helpers for budgets and transaction splits to quickly pick existing categories.

### Changed

- Reused transaction category suggestions across budgets and splits for a consistent selection experience.

### Fixed

- Budget calculations skip parent split transactions to prevent double counting and keep aggregates accurate.

## [0.6.9] - 2025-01-07

### Added

- Added a contextual right-click menu on transactions with Auto-categorize, Edit category, and Split transaction actions.
- Introduced transaction splitting with a guided modal, automatic remainder balancing, and category helper dropdowns.
- Persist parent/child relationships for split transactions, including schema migration and API support.

### Changed

- Automatically rescale child split amounts when Plaid updates the parent transaction amount.
- Block split operations on child transactions to prevent nested splits and ensure data integrity.

### Fixed

- Synced splits now remove or flag child rows when the parent transaction is deleted or refreshed from Plaid.

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