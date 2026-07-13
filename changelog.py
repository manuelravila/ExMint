# changelog.py — Structured release history for exMint
# Each entry: {version, date, changes: [str]}

changelog = [
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
