# changelog.py — Structured release history for exMint
# Each entry: {version, date, changes: [str]}

changelog = [
    {
        "version": "1.14.1",
        "date": "2026-10-10",
        "changes": [
            "Money amounts no longer wrap: a large negative amount in a narrow column (for example "
            "-CA$35,000.00) showed the minus sign on its own line above the number. Applies to the "
            "transactions table, the selected subtotal, balances, spending totals and project cards"
        ]
    },
    {
        "version": "1.14.0",
        "date": "2026-10-10",
        "changes": [
            "CSV import checks the amount signs before saving anything. If the file would be stored reversed "
            "(rows matching existing transactions with the opposite sign, card payments or refunds saved as money "
            "out, or a card statement that is mostly money in), the import stops and offers to switch the sign "
            "setting, or to import as chosen after a second confirmation. The machine API import does the same "
            "and accepts sign_confirmed",
            "Machine API: list and create projects (GET/POST /api/v1/projects) and assign transactions to a "
            "project (PATCH /api/v1/transactions/bulk-project), with the same rules as the dashboard"
        ]
    },
    {
        "version": "1.13.0",
        "date": "2026-10-10",
        "changes": [
            "Transactions list shows the net total of every transaction matching the current filters "
            "(all pages, not just the one on screen), next to the transaction count",
            "When transactions are selected, the toolbar shows the subtotal of the selected rows next to the "
            "selected count"
        ]
    },
    {
        "version": "1.12.0",
        "date": "2026-10-09",
        "changes": [
            "Projects: group any set of transactions into a named project (for example a trip or a renovation). "
            "A transaction belongs to at most one project; deleting a project keeps its transactions and only "
            "unassigns them",
            "New Projects tab on the Dashboard: create, rename, recolor and delete projects, and see each project's "
            "net total with year and month subtotals (years appear when a project spans more than one year, months "
            "when it spans more than one month). Click any total to open exactly those transactions",
            "Select transactions and use Assign project in the toolbar to add them to a project, start a new one, or "
            "remove them from their project; rows show a project tag",
            "The transactions list and its CSV/Excel export can be filtered by project (or No project); splitting a "
            "transaction copies its project onto the split parts",
            "A category can be linked to one project (Categories list, Project column): every transaction of that "
            "category then counts in the project too, while a transaction assigned to a project by hand keeps its own. "
            "Project cards list the categories they include",
            "Project cards are laid out side by side (two or more per row, depending on the screen)",
            "Regression test: re-applying category rules never reverses a manual category or a split"
        ]
    },
    {
        "version": "1.11.0",
        "date": "2026-10-08",
        "changes": [
            "CSV import now tolerates a metadata preamble before the real header row, and maps columns by scored "
            "alias matching instead of the first alias that happens to overlap, so a field like transaction amount "
            "resolves to amount rather than description",
            "Quoted account and card numbers are normalized with their quote characters stripped; before this, a "
            "quoted card number produced an account whose stored mask ended in a stray quote and no rows matched it",
            "New amount_sign import option with values 'as_is' (default) and 'invert' for files that write spending "
            "as positive while ExMint stores money out as negative; such files used to import with the sign inverted, "
            "which also made the cross-source dedup unable to match already-synced rows since it compares amounts "
            "for exact equality",
            "The import modal now asks which sign convention the file uses",
            "Dedup is now count-aware so a statement containing the same date, amount and description twice stores "
            "both rows instead of dropping the second, while re-importing a byte-identical file still inserts "
            "nothing, and the Plaid-overlap guard keeps a per-key budget for the run",
            "Analyze now returns date_candidates and the modal warns when a file carries more than one date column, "
            "since only the mapped column decides the ledger date and synced credit-card rows are dated by posting date"
        ]
    },
    {
        "version": "1.10.5",
        "date": "2026-10-08",
        "changes": [
            "Plaid sync fix: reconnecting a paused (soft-disconnected) institution now discards the stored "
            "transactions cursor when Plaid assigns a new Item. A Plaid cursor is scoped to the Item that "
            "produced it, so replaying a cursor from a removed Item causes errors or an incomplete transaction "
            "history; the reconnect now drops it and the next sync bootstraps a fresh cursor."
        ]
    },
    {
        "version": "1.10.4",
        "date": "2026-10-08",
        "changes": [
            "Security patch: bumped Flask 3.1.3, Werkzeug 3.1.9, Jinja2 3.1.6, Mako 1.4.3, urllib3 2.8.0, requests 2.34.2, "
            "idna 3.15, PyJWT 2.15.1, Flask-Cors 6.0.5, cryptography 50.0.2, filelock 3.20.3 to clear 100 open OSV advisories "
            "(incl. PyJWT critical token-forgery CVE-2026-102268 and six urllib3 HIGH decompression-bomb/redirect issues)"
        ]
    },
    {
        "version": "1.10.3",
        "date": "2026-10-07",
        "changes": [
            "Spending Report: a category with a budget but no spending in the displayed month now shows its "
            "real trailing 6-month average instead of 0 (fixes budget-only rows showing 6M Average = 0)"
        ]
    },
    {
        "version": "1.10.2",
        "date": "2026-10-07",
        "changes": [
            "Auto-categorize on a transaction that was categorized by a rule now jumps to the exact "
            "rule row that decided it (the specificity winner), not just the category"
        ]
    },
    {
        "version": "1.10.1",
        "date": "2026-10-07",
        "changes": [
            "Fixes the v1.10.0 regression that broke the Automatic rules tab and the Auto-categorize "
            "transaction menu (missing Vue state and conflict-fetch method in the release commit)"
        ]
    },
    {
        "version": "1.10.0",
        "date": "2026-10-07",
        "changes": [
            "Hidden (eye) categories are now hidden from Income too, not just from Expenses: excluded "
            "categories appear dimmed in the income section with their own toggle and no longer inflate "
            "the income subtotal",
            "Automatic rules now resolve conflicts by specificity instead of creation order: amount-bounded "
            "rules beat unbounded ones, longer match text beats shorter, so 'PAYMENT FROM' >= $1000 wins "
            "over a bare 'Deposit' rule",
            "New overlap alerts: when two rules match the same transactions but target different "
            "categories, the rules page shows a warning listing each overlap with affected counts "
            "and sample transactions, a warning icon marks the overridden rule, and saving a new "
            "overlapping rule shows an immediate notice so you can adjust rules to keep them unique"
        ]
    },
    {
        "version": "1.9.0",
        "date": "2026-09-15",
        "changes": [
            "CSV import can auto-create accounts for unrecognised account numbers (opt-in)",
            "New-account institution is inferred from the file when every matched row belongs to one "
            "institution; otherwise the user must choose — the import never guesses",
            "Auto-created accounts use an idempotent get-or-create: re-importing a file reuses the account instead of duplicating it",
            "New optional 'account type' CSV mapping sets the subtype of accounts the import creates (existing accounts are never modified)",
            "Plaid linking now recognises CSV-auto-created accounts by institution + mask, re-parenting them instead of creating a duplicate"
        ]
    },
    {
        "version": "1.8.2",
        "date": "2026-09-15",
        "changes": [
            "CSV import no longer 500s on rows whose account number matches no account — such rows are reported per-row instead of aborting the import",
            "A failed row no longer poisons the whole import: the SQLAlchemy session is rolled back per row",
            "Row errors now name the offending account number so the bad row is easy to find",
            "The import dialog offers a fallback account so rows with an unmatched account number can still be imported",
            "Import failures now show a readable message instead of a JSON parse error"
        ]
    },
    {
        "version": "1.8.1",
        "date": "2026-07-13",
        "changes": [
            "Excluded categories now stay visible in table (strikethrough+dim) instead of disappearing",
            "Override-to-excluded leak fixed — transactions overridden to excluded categories (e.g. Vehicle→Transfer) now properly excluded",
            "Duplicate Everything Else row fixed — budget-only lines no longer add EE, handled solely by dedicated section",
            "Everything Else now shows even with $0 uncategorized spending (if a budget exists)",
            "Header labels reordered: Total → Budget → Remainder",
            "Remainder turns green (positive) or red (negative) instead of always orange",
            "Remainder now calculated as Budget − Total (not sum of per-category remainders)",
            "Clicking Everything Else searches uncategorized transactions (instead of returning no results)",
            "Budget-exclusion check honours transaction overrides (not just custom_category_id)"
        ]
    },
    {
        "version": "1.8.0",
        "date": "2026-07-13",
        "changes": [
            "Flexible budget system with rollover — monthly surplus rolls to next month proportionally",
            "Net-gate rollover: surplus only distributes if total spending stays under total budget",
            "Everything Else virtual bucket — aggregates budget-excluded categories into one line item",
            "Budget-exclusion toggle (eye icon) per category — excluded transactions skip budget tracking",
            "Auto-rollover on first dashboard load after month transition",
            "Alembic migration: budget_excluded, is_automatic, rollover_amount columns",
            "Spending report shows rollover amounts as green +$X badges with base budget breakdown"
        ]
    },
    {
        "version": "1.6.0",
        "date": "2026-07-01",
        "changes": [
            "Per-month budgets with MonthlyBudget table — budgets tied to individual months instead of global",
            "Spending header now shows Budget: $X | Remainder: $X | Balance: $X per month",
            "Budget propagation fills forward into blank future months only, never overwrites existing entries",
            "Auto-creation copies budgets from previous month when new months get transactions",
            "Backward-fallback fix: months before the earliest budget show no budget (not the earliest entry)"
        ]
    },
    {
        "version": "1.5.6",
        "date": "2026-06-30",
        "changes": [
            "Fixed spending report showing empty months — backend now correctly splits income/spending categories",
            "CSV import dedup catches Plaid+CSV overlap by (account, date, amount) ignoring name differences",
            "Find Duplicates (Maintenance) detects Plaid+CSV overlap as a third duplicate class"
        ]
    },
    {
        "version": "1.5.5",
        "date": "2026-06-30",
        "changes": [
            "Spending Report now shows income categories separately with green header, spending in purple",
            "Net difference (income - spending) shown in month header",
            "Income/spending section headers have tinted background and sit flush against their tables"
        ]
    },
    {
        "version": "1.5.4",
        "date": "2026-06-30",
        "changes": [
            "CSV import dedup now catches Plaid+CSV overlap — second pass by (account, date, amount) prevents duplicate imports",
            "Find Duplicates (Maintenance) detects Plaid+CSV overlap groups as a third duplicate class"
        ]
    },
    {
        "version": "1.5.3",
        "date": "2026-06-30",
        "changes": [
            "30-minute idle session timeout — auto-logout after inactivity",
            "Server tracks _last_active per request; 401 redirects to /login",
            "Combined with existing 4-hour hard ceiling (whichever fires first)"
        ]
    },
    {
        "version": "1.5.2",
        "date": "2026-06-30",
        "changes": [
            "Session now expires after 4 hours — login page appears automatically",
            "Added changelog page (click the version number in the footer)",
            "Frontend auto-redirects to login when session expires (no more broken UI)"
        ]
    },
    {
        "version": "1.5.1",
        "date": "2026-06-28",
        "changes": [
            "Soft disconnect (pause institution) — keep CSV import while pausing Plaid sync",
            "API v1 endpoints for CSV import (programmatic access)",
            "Bulk category assignment across selected transactions",
            "Reconnection flow for paused institutions"
        ]
    },
    {
        "version": "1.5.0",
        "date": "2026-06-22",
        "changes": [
            "CSV import with column auto-detection",
            "Multi-account CSV routing by last 4 digits",
            "Category rules auto-apply after CSV import",
            "Multi-currency support (CAD/USD) on import",
            "Category suggestion on transaction click",
            "Auto-categorization rules with re-evaluation"
        ]
    },
    {
        "version": "1.4.4",
        "date": "2026-06-15",
        "changes": [
            "Fixed selection state leak on data refresh",
            "Fixed template-scoping bug in computed properties",
            "Export transactions to CSV and Excel"
        ]
    },
    {
        "version": "1.4.3",
        "date": "2026-06-10",
        "changes": [
            "Sync summary notifications after Plaid sync",
            "Mobile sidebar improvements",
            "Performance optimizations for large transaction sets"
        ]
    },
    {
        "version": "1.4.2",
        "date": "2026-06-05",
        "changes": [
            "Budget tracking per category",
            "Spending analysis on dashboard",
            "Category color customization"
        ]
    },
    {
        "version": "1.4.1",
        "date": "2026-05-28",
        "changes": [
            "CSV import preview fix (header names vs cell data)",
            "Enhanced Plaid error handling",
            "Fixed filter persistence across page reloads"
        ]
    },
    {
        "version": "1.4.0",
        "date": "2026-05-20",
        "changes": [
            "Initial CSV import feature",
            "Auto-categorization rules",
            "Transaction search and filtering overhaul",
            "Custom categories with color labels"
        ]
    },
    {
        "version": "1.3.0",
        "date": "2026-05-10",
        "changes": [
            "Plaid Link integration for bank connections",
            "Multi-institution support",
            "Account management (enable/disable)",
            "Date range filtering on transactions"
        ]
    },
    {
        "version": "1.2.0",
        "date": "2026-04-28",
        "changes": [
            "User registration and approval workflow",
            "Admin panel for user management",
            "Password reset via email"
        ]
    },
    {
        "version": "1.1.0",
        "date": "2026-04-15",
        "changes": [
            "Dashboard with balance overview",
            "Transaction list with pagination",
            "Basic transaction categorization"
        ]
    },
    {
        "version": "1.0.0",
        "date": "2026-04-01",
        "changes": [
            "Initial release — Plaid transaction sync",
            "User authentication system",
            "Basic account management"
        ]
    }
]
