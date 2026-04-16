//vuePlaid.js
Vue.component('line-chart', {
  extends: window.VueChartJs.Line,
  props: ['chartData', 'options'],
  watch: {
    chartData () {
      this.$data._chart.destroy()
      this.renderChart(this.chartData, this.options)
    }
  },
  mounted () {
    this.renderChart(this.chartData, this.options)
  }
})

const linkButton = document.getElementById('link-button');
let linkHandler = null;

// Function to handle the creation of the link token, adapted to support update mode.
// Pass credential_id when reconnecting an existing bank so the backend can look up
// the access token internally without exposing it to the browser.
async function createLinkToken(access_token = null, credential_id = null) {
    const payload = {};
    if (access_token) {
        payload.access_token = access_token;
    }
    if (credential_id) {
        payload.credential_id = credential_id;
    }
    const response = await fetch('/create_link_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (!response.ok) {
        console.error("Failed to create link token:", response.statusText);
        throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data.link_token;
}


// Global variable to store the access token
let accessToken = null;

// Function to initialize Plaid Link
async function initializeLink() {
    const linkToken = await createLinkToken();
    console.log("Received link token:", linkToken);
    console.log(linkToken);  // Add this line for debugging
    linkHandler = Plaid.create({
        token: linkToken,
        onSuccess: async (publicToken, metadata) => {
            // Send the public token to the server
            const institutionName = metadata.institution.name;  // Get institution name from metadata
            const response = await fetch('/handle_token_and_accounts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ public_token: publicToken, institution_name: institutionName }),
            });
            const data = await response.json();

            console.log("Get Access Token Response:", data); // Debugging: log the response from get access token

            // After receiving the access token
            accessToken = data.access_token;  // Set the access token
            console.log("Access Token:", accessToken);  // Debugging: log the access token

            if (response.ok && data.status === 'success') {
                if (typeof app !== 'undefined') {
                    if (typeof app.refreshData === 'function') {
                        await app.refreshData();
                    } else if (typeof app.fetchBanks === 'function') {
                        await app.fetchBanks();
                        if (typeof app.fetchTransactions === 'function') {
                            await app.fetchTransactions();
                        }
                    }
                } else {
                    console.error("Vue instance 'app' is not defined.");
                    setTimeout(() => {
                        window.location.href = '/dashboard';
                    }, 500);
                }
            } else if (response.status === 409) {
                const msg = data.error || 'This bank is already connected. Use the reconnect option to refresh it instead.';
                alert(msg);
                if (typeof app !== 'undefined') {
                    app.connectionWarning = msg;
                }
            } else {
                // Handle error scenario
                console.error('Error adding bank connection:', data.error || 'Unknown error');
                alert('Failed to add bank connection. Please try again.');
            }
        },
        // Add other Plaid Link configuration options here
    });
    console.log("Plaid Link initialized", linkHandler);
}

// Function to initiate the reconnect process for a bank.
// The access token is never sent to the browser; the backend resolves it from credential_id.
async function reconnectBank(bankId) {
    try {
        const linkToken = await createLinkToken(null, bankId);

        linkHandler = Plaid.create({
            token: linkToken,
            onSuccess: async (publicToken, metadata) => {
                const refreshResponse = await fetch('/handle_token_and_accounts', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        public_token: publicToken,
                        institution_name: metadata.institution.name,
                        is_refresh: true,
                        credential_id: bankId
                    })
                });
                if (refreshResponse.ok) {
                    if (typeof app !== 'undefined' && typeof app.refreshData === 'function') {
                        await app.refreshData();
                    } else {
                        window.location.href = '/dashboard';
                    }
                } else {
                    console.error("Failed to refresh accounts");
                }
            },
            onExit: (err, metadata) => console.log("User exited link modal", err, metadata)
        });

        linkHandler.open();
    } catch (error) {
        console.error("Error during bank reconnect:", error);
    }
}

// Initialize Plaid Link after Vue instance
async function initializePlaidLink() {
    try {
        await initializeLink();
        //console.log("Plaid Link initialized", linkHandler);
    } catch (error) {
        console.error("Error initializing Plaid Link:", error);
    }
}


const app = new Vue({
    el: '#vue-app',
    delimiters: ['[[', ']]'],
    data: {
        banks: [],
        selectedAccountIds: [],
        transactions: [],
        categoryRules: [],
        customCategories: [],
        categoryLabels: [],
        categoriesError: null,
        customCategoriesError: null,
        filters: {
            search: '',
            sortKey: 'date',
            sortDesc: true,
            startDate: '',
            endDate: '',
            customCategoryId: '',
            amountMin: '',
            amountMax: ''
        },
        syncing: false,
        loading: true,
        syncSummary: [],
        syncErrors: [],
        connectionWarning: null,
        modalBanks: [],
        openInstitutionIds: [],
        transactionsPage: 1,
        transactionsPageSize: 200,
        transactionsTotal: 0,
        hasMoreTransactions: false,
        searchDebounce: null,
        transactionsRequestToken: 0,
        activePane: 'dashboard',
        transactionsCollapsed: false,
        categoriesLoading: false,
        categoriesLoaded: false,
        customCategoriesLoading: false,
        customCategoriesLoaded: false,
        categoryTab: 'manage',
        nextCategoryTempId: 0,
        nextCustomCategoryTempId: 0,
        openCategoryColorId: null,
        categoryPalette: [
            '#2C6B4F', '#F94144', '#F3722C', '#F8961E',
            '#F9844A', '#F9C74F', '#90BE6D', '#43AA8B',
            '#4D908E', '#577590', '#277DA1', '#6D597A',
            '#B56576', '#E56B6F', '#EAAC8B', '#9A031E',
            '#5F0F40', '#FB8B24', '#4361EE', '#3A86FF',
            '#8338EC', '#FF006E', '#FFBF69', '#8AC926'
        ],
        editingTransactionCategoryId: null,
        editingTransactionCategoryValue: '',
        transactionCategoryBlurTimeout: null,
        selectedTransactionIds: [],
        bulkCategoryValue: '',
        bulkCategoryApplying: false,
        transactionMenu: {
            visible: false,
            x: 0,
            y: 0,
            transaction: null
        },
        touchContextMenuTimer: null,
        touchContextMenuTriggered: false,
        touchContextMenuStart: null,
        highlightedRuleLocalId: null,
        highlightedRuleTimeout: null,
        highlightedCategoryLocalId: null,
        highlightedCategoryTimeout: null,
        splitModal: {
            visible: false,
            transaction: null,
            rows: [],
            parentAmountCents: 0,
            errors: [],
            saving: false
        },
        splitCategoryDropdown: {
            rowId: null,
            items: []
        },
        splitCategoryBlurTimeout: null,
        budgets: [],
        budgetsLoading: false,
        budgetsLoaded: false,
        budgetsError: null,
        budgetSummary: {
            income_total: 0,
            expense_total: 0,
            net_total: 0
        },
        budgetFrequencies: [
            { value: 'monthly', label: 'Monthly' },
            { value: 'semi-monthly', label: 'Semi-Monthly' },
            { value: 'biweekly', label: 'Biweekly' },
            { value: 'weekly', label: 'Weekly' },
            { value: 'quarterly', label: 'Quarterly' },
            { value: 'yearly', label: 'Yearly' }
        ],
        budgetCategoryDropdown: {
            rowId: null,
            items: []
        },
        budgetCategoryBlurTimeout: null,
        nextBudgetTempId: 0,
        dashboardLoading: false,
        dashboardLoaded: false,
        dashboardError: null,
        dashboardData: {
            balances: { groups: [], grand_total: 0 },
            spending: { years: [], current_year: null, current_month: null },
            cashflow: { months: [], categories: [], series: {} }
        },
        selectedCashflowCategory: 'all',
        openBalanceGroups: [],
        openBalanceInstitutions: {},
        selectedSpendingYear: null,
        openSpendingMonths: {},
        dashboardTab: 'summary',
        nextSplitRowId: 0,
        isSidebarCollapsed: false,
        isMobileView: false,
        mobileCardCollapsed: {
            balances: false,
            spending: false
        },
        lastDesktopSidebarPreference: null,
        mobileSidebarVisible: false,
        maintenance: {
            scanning: false,
            deduplicating: false,
            duplicateGroups: null,
            totalDuplicates: 0,
            scanError: null,
            deduplicationResult: null,
        }
    },
    computed: {
        totalAccountCount: function() {
            return this.banks.reduce((count, bank) => count + bank.accounts.length, 0);
        },
        areAllAccountsSelected: function() {
            return this.totalAccountCount > 0 && this.selectedAccountIds.length === this.totalAccountCount;
        },
        displayedTransactions: function() {
            if (!this.selectedAccountIds.length) {
                return [];
            }
            return this.transactions;
        },
        showingRange: function() {
            if (!this.transactions.length || !this.transactionsTotal) {
                return { start: 0, end: 0 };
            }
            const start = (this.transactionsPage - 1) * this.transactionsPageSize + 1;
            const end = start + this.transactions.length - 1;
            return { start, end };
        },
        totalPages: function() {
            if (!this.transactionsTotal) {
                return 1;
            }
            return Math.max(1, Math.ceil(this.transactionsTotal / this.transactionsPageSize));
        },
        showPagination: function() {
            return this.transactionsTotal > this.transactionsPageSize;
        },
        transactionCategoryOptions: function() {
            const unique = new Map();
            this.customCategories.forEach(category => {
                if (!category || !category.name) {
                    return;
                }
                const key = category.name.trim().toLowerCase();
                if (!unique.has(key)) {
                    unique.set(key, category.name.trim());
                }
            });
            return Array.from(unique.values()).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
        },
        availableBudgetCategories: function() {
            // Custom categories that don't yet have a saved budget — used to populate
            // the category dropdown when adding a new budget row.
            const budgeted = new Set(
                this.budgets
                    .filter(b => b.id)
                    .map(b => (b.category_label || '').trim().toLowerCase())
            );
            return this.transactionCategoryOptions.filter(
                opt => !budgeted.has((opt || '').trim().toLowerCase())
            );
        },
        customCategoryFilterOptions: function() {
            return this.customCategories
                .filter(category => category && category.id && category.name)
                .map(category => ({
                    id: String(category.id),
                    label: category.name
                }))
                .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
        },
        hasActiveTransactionFilters: function() {
            const defaults = {
                search: '',
                sortKey: 'date',
                sortDesc: true,
                startDate: '',
                endDate: '',
                customCategoryId: '',
                amountMin: '',
                amountMax: ''
            };
            return Object.keys(defaults).some(key => this.filters[key] !== defaults[key]);
        },
        filteredTransactionSuggestions: function() {
            if (this.editingTransactionCategoryId === null) {
                return [];
            }
            const query = (this.editingTransactionCategoryValue || '').trim().toLowerCase();
            const options = this.transactionCategoryOptions;
            if (!query) {
                return options.slice(0, 8);
            }
            return options.filter(option => option.toLowerCase().includes(query)).slice(0, 8);
        },
        areAllDisplayedTransactionsSelected: function() {
            if (!this.displayedTransactions.length) return false;
            return this.displayedTransactions.every(t => this.selectedTransactionIds.indexOf(t.id) !== -1);
        },
        selectedTransactionIdSet: function() {
            return new Set(this.selectedTransactionIds);
        },
        filteredBulkCategorySuggestions: function() {
            const query = (this.bulkCategoryValue || '').trim().toLowerCase();
            const options = this.transactionCategoryOptions;
            if (!query) return options.slice(0, 8);
            return options.filter(o => o.toLowerCase().includes(query)).slice(0, 8);
        },
        splitModalRemainingCents: function() {
            if (!this.splitModal.visible) {
                return 0;
            }
            const parent = this.splitModal.parentAmountCents || 0;
            const total = this.splitModal.rows.reduce((sum, row) => {
                const cents = this.parseAmountToCents(row.amount);
                if (cents === null) {
                    return sum;
                }
                return sum + cents;
            }, 0);
            return parent - total;
        },
        canSubmitSplit: function() {
            if (!this.splitModal.visible) {
                return false;
            }
            if (this.splitModal.saving) {
                return false;
            }
            return this.splitModal.errors.length === 0;
        },
        hasNewTransactions: function() {
            return this.transactions.some(txn => txn.is_new);
        },
        splitCategoryOptions: function() {
            return this.transactionCategoryOptions;
        },
        spendingYearOptions: function() {
            const spending = this.dashboardData.spending || {};
            const years = spending.years || [];
            return years.map(entry => entry.year).sort((a, b) => b - a);
        },
        filteredSpendingMonths: function() {
            if (!this.selectedSpendingYear) {
                return [];
            }
            const spending = this.dashboardData.spending || {};
            const years = spending.years || [];
            const yearEntry = years.find(entry => entry.year === this.selectedSpendingYear);
            if (!yearEntry) {
                return [];
            }
            const months = yearEntry.months || [];
            return months.slice().sort((a, b) => b.month - a.month);
        },
        filteredCashflowMonths: function() {
            const cashflow = this.dashboardData.cashflow || {};
            const months = Array.isArray(cashflow.months) ? cashflow.months : [];
            if (this.selectedCashflowCategory === 'all') {
                return months.map(month => ({
                    ...month,
                    total: Number(month.total || 0)
                }));
            }
            const series = cashflow.series || {};
            const data = series[this.selectedCashflowCategory] || {};
            return months.map(month => {
                const value = Number(data[month.key] || 0);
                
                // When a category is selected, we need to recalculate the series for the bar chart.
                const new_series = {
                    positive: { value: Math.max(0, value), color: '#2C6B4F' },
                    negative: { value: Math.abs(Math.min(0, value)), color: '#F94144' }
                };

                return {
                    ...month,
                    total: value,
                    series: new_series
                };
            });
        },
        cashflowChartData: function() {
            const labels = this.filteredCashflowMonths.map(month => month.label);
            const data = this.filteredCashflowMonths.map(month => month.total);
            return {
                labels: labels,
                datasets: [
                    {
                        label: 'Cash Flow',
                        backgroundColor: '#2C6B4F',
                        borderColor: '#2C6B4F',
                        data: data,
                        fill: false,
                    }
                ]
            }
        },
        cashflowChartOptions: function() {
            return {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    yAxes: [{
                        ticks: {
                            beginAtZero: true
                        }
                    }]
                }
            }
        }
    },
    methods: {
        markAsSeen: async function(transaction) {
            if (!transaction || !transaction.is_new) {
                return;
            }
        
            // Optimistically update the UI
            transaction.is_new = false;
        
            try {
                const response = await fetch('/api/transactions/mark_as_seen', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ transaction_ids: [transaction.id] })
                });
                if (!response.ok) {
                    // Revert on failure
                    transaction.is_new = true;
                }
            } catch (error) {
                console.error('Error marking transaction as seen:', error);
                // Revert on failure
                transaction.is_new = true;
            }
        },
        refreshData: async function() {
            this.loading = true;
            try {
                await this.fetchBanks();
                await this.fetchCustomCategories({ suppressLoader: true });
                await this.fetchTransactions({ reset: true, skipLoadingState: true });
                if (this.activePane === 'categories') {
                    await this.fetchCategories({ refresh: true, suppressLoader: true });
                }
                if (this.budgetsLoaded) {
                    await this.fetchBudgets({ suppressLoader: true, force: true, refreshOnly: true });
                }
                if (this.dashboardLoaded) {
                    await this.fetchDashboard({ suppressLoader: true, force: true });
                }
            } finally {
                this.loading = false;
                this.$nextTick(() => {
                    this.updateInstitutionCheckboxStates();
                    this.updateStickyPositions();
                });
            }
        },
        setActivePane: async function(pane) {
            if (this.activePane === pane) {
                return;
            }
            this.activePane = pane;
            if (this.isMobileView && this.mobileSidebarVisible) {
                this.closeMobileSidebar();
            }
            if (pane !== 'transactions') {
                this.cancelTransactionCategoryEdit();
            }
            if (pane !== 'budgets') {
                this.closeBudgetCategoryDropdown();
            }
            if (pane !== 'dashboard') {
                this.dashboardError = null;
            }
            if (pane === 'categories') {
                if (!this.categoriesLoaded || (!this.categoryRules.length && !this.categoriesLoading)) {
                    await this.fetchCategories();
                }
            } else if (pane === 'budgets') {
                if (!this.budgetsLoaded || (!this.budgets.length && !this.budgetsLoading)) {
                    await this.fetchBudgets();
                }
                if (!this.customCategoriesLoaded) {
                    await this.fetchCustomCategories({ suppressLoader: true });
                }
            } else if (pane === 'dashboard') {
                if (!this.dashboardLoaded || !this.dashboardData || !this.dashboardData.balances.groups.length) {
                    await this.fetchDashboard();
                }
            } else if (pane === 'transactions' && this.selectedAccountIds.length) {
                if (!this.transactions.length) {
                    await this.fetchTransactions({ reset: true });
                }
            }
            this.$nextTick(() => {
                this.updateStickyPositions();
            });
        },
        setCategoryTab: async function(tab) {
            if (this.categoryTab === tab) {
                return;
            }
            this.categoryTab = tab;
            if (tab !== 'manage' && this.openCategoryColorId !== null) {
                this.openCategoryColorId = null;
            }
            if (tab === 'manage') {
                if (!this.customCategoriesLoaded) {
                    await this.fetchCustomCategories();
                }
            } else if (tab === 'rules') {
                if (!this.categoriesLoaded) {
                    await this.fetchCategoryRules();
                }
            }
        },
        toggleTransactionsCollapse: function() {
            this.transactionsCollapsed = !this.transactionsCollapsed;
            this.$nextTick(() => {
                this.updateStickyPositions();
            });
        },
        toggleSidebarCollapse: function() {
            if (this.isMobileView) {
                return;
            }
            this.isSidebarCollapsed = !this.isSidebarCollapsed;
            this.lastDesktopSidebarPreference = this.isSidebarCollapsed;
            this.persistSidebarState();
            this.$nextTick(() => {
                this.updateStickyPositions();
            });
        },
        toggleMobileSidebar: function() {
            if (!this.isMobileView) {
                return;
            }
            this.mobileSidebarVisible = !this.mobileSidebarVisible;
            if (this.mobileSidebarVisible) {
                this.transactionsCollapsed = false;
            }
        },
        closeMobileSidebar: function() {
            if (!this.mobileSidebarVisible) {
                return;
            }
            this.mobileSidebarVisible = false;
        },
        sidebarTooltip: function(label) {
            if (this.isMobileView) {
                return null;
            }
            return this.isSidebarCollapsed ? label : null;
        },
        initializeSidebarState: function() {
            try {
                const stored = window.localStorage.getItem('exmintSidebarCollapsed');
                if (stored !== null) {
                    this.isSidebarCollapsed = stored === 'true';
                }
                this.lastDesktopSidebarPreference = this.isSidebarCollapsed;
            } catch (error) {
                // Silently ignore storage issues to avoid degrading UX.
            }
        },
        persistSidebarState: function() {
            try {
                window.localStorage.setItem('exmintSidebarCollapsed', this.isSidebarCollapsed ? 'true' : 'false');
            } catch (error) {
                // Silently ignore storage issues to avoid degrading UX.
            }
        },
        evaluateViewportState: function() {
            if (typeof window === 'undefined') {
                return;
            }
            const isMobile = window.innerWidth < 992;
            if (isMobile && !this.isMobileView) {
                this.lastDesktopSidebarPreference = this.isSidebarCollapsed;
                if (this.isSidebarCollapsed) {
                    this.isSidebarCollapsed = false;
                }
                this.mobileCardCollapsed.balances = false;
                this.mobileCardCollapsed.spending = false;
            } else if (!isMobile && this.isMobileView) {
                if (this.lastDesktopSidebarPreference !== null) {
                    this.isSidebarCollapsed = this.lastDesktopSidebarPreference;
                }
            }
            this.isMobileView = isMobile;
            if (!isMobile) {
                this.mobileSidebarVisible = false;
                this.mobileCardCollapsed.balances = false;
                this.mobileCardCollapsed.spending = false;
            } else {
                this.mobileSidebarVisible = false;
            }
        },
        toggleMobileCard: function(card) {
            if (!this.isMobileView || !this.mobileCardCollapsed.hasOwnProperty(card)) {
                return;
            }
            this.$set(this.mobileCardCollapsed, card, !this.mobileCardCollapsed[card]);
        },
        fetchDashboard: async function(options = {}) {
            const { suppressLoader = false, force = false } = options;
            if (this.dashboardLoading) {
                return;
            }
            if (this.dashboardLoaded && !force) {
                return;
            }
            if (!suppressLoader) {
                this.dashboardLoading = true;
            }
            this.dashboardError = null;
            try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to load dashboard.');
                }
                this.dashboardData = {
                    balances: data.balances || { groups: [], grand_total: 0 },
                    spending: data.spending || { years: [], current_year: null, current_month: null },
                    cashflow: data.cashflow || { months: [], categories: [], series: {} }
                };
                this.dashboardLoaded = true;
                this.initializeDashboardState();
            } catch (error) {
                console.error('Error fetching dashboard:', error);
                this.dashboardError = error.message || 'Failed to load dashboard.';
            } finally {
                if (!suppressLoader) {
                    this.dashboardLoading = false;
                }
            }
        },
        initializeDashboardState: function() {
            const balances = this.dashboardData.balances || {};
            this.openBalanceGroups = (balances.groups || []).map(group => group.key);
            this.openBalanceInstitutions = {};
            (balances.groups || []).forEach(group => {
                const ids = (group.institutions || []).map(inst => inst.id);
                this.$set(this.openBalanceInstitutions, group.key, ids);
            });

            const spending = this.dashboardData.spending || {};
            const years = spending.years || [];
            const yearOptions = years.map(y => y.year).sort((a, b) => b - a);

            let defaultYear = spending.current_year;
            if (!yearOptions.includes(defaultYear)) defaultYear = yearOptions[0] || null;
            this.selectedSpendingYear = defaultYear;
            this.openSpendingMonths = {};
            if (defaultYear !== null) {
                this.resetOpenSpendingMonths();
            }

            const cashflow = this.dashboardData.cashflow || {};
            if (!this.selectedCashflowCategory || this.selectedCashflowCategory === 'all') {
                this.selectedCashflowCategory = 'all';
            } else if (!Array.isArray(cashflow.categories) || !cashflow.categories.some(cat => cat.key === this.selectedCashflowCategory)) {
                this.selectedCashflowCategory = 'all';
            }
        },
        isBalanceGroupOpen: function(key) {
            return this.openBalanceGroups.includes(key);
        },
        toggleBalanceGroup: function(key) {
            if (!key) {
                return;
            }
            if (this.isBalanceGroupOpen(key)) {
                this.openBalanceGroups = this.openBalanceGroups.filter(item => item !== key);
            } else {
                this.openBalanceGroups = [...this.openBalanceGroups, key];
            }
        },
        isBalanceInstitutionOpen: function(groupKey, institutionId) {
            const entries = this.openBalanceInstitutions[groupKey] || [];
            return entries.includes(institutionId);
        },
        toggleBalanceInstitution: function(groupKey, institutionId) {
            if (!groupKey || !institutionId) {
                return;
            }
            const entries = this.openBalanceInstitutions[groupKey] || [];
            if (entries.includes(institutionId)) {
                this.$set(this.openBalanceInstitutions, groupKey, entries.filter(item => item !== institutionId));
            } else {
                this.$set(this.openBalanceInstitutions, groupKey, [...entries, institutionId]);
            }
        },
        setDashboardTab: function(tab) {
            this.dashboardTab = tab;
        },
        handleSpendingYearChange: function() {
            this.resetOpenSpendingMonths();
        },
        resetOpenSpendingMonths: function() {
            if (!this.selectedSpendingYear) {
                return;
            }
            const spending = this.dashboardData.spending || {};
            const years = spending.years || [];
            const yearEntry = years.find(entry => entry.year === this.selectedSpendingYear);
            if (!yearEntry) {
                this.$set(this.openSpendingMonths, this.selectedSpendingYear, []);
                return;
            }
            const months = (yearEntry.months || []).slice().sort((a, b) => b.month - a.month);
            if (!months.length) {
                this.$set(this.openSpendingMonths, this.selectedSpendingYear, []);
                return;
            }
            let defaultMonth = months[0].month;
            if (spending.current_year === this.selectedSpendingYear && spending.current_month) {
                const match = months.find(month => month.month === spending.current_month);
                if (match) {
                    defaultMonth = spending.current_month;
                }
            }
            this.$set(this.openSpendingMonths, this.selectedSpendingYear, defaultMonth != null ? [defaultMonth] : []);
        },
        isSpendingMonthOpen: function(year, month) {
            const months = this.openSpendingMonths[year] || [];
            return months.includes(month);
        },
        toggleSpendingMonth: function(year, month) {
            const months = this.openSpendingMonths[year] || [];
            if (months.includes(month)) {
                this.$set(this.openSpendingMonths, year, months.filter(item => item !== month));
            } else {
                this.$set(this.openSpendingMonths, year, [...months, month]);
            }
        },
        getSpendingCategoriesForMonth: function(month) {
            if (!month || !Array.isArray(month.categories)) {
                return [];
            }
            return month.categories;
        },

        startTransactionCategoryEdit: function(transaction) {
            if (!transaction || transaction.savingCategory) {
                return;
            }
            this.editingTransactionCategoryId = transaction.id;
            this.editingTransactionCategoryValue = transaction.custom_category || '';
            this.$nextTick(() => {
                const refName = `transactionCategoryInput-${transaction.id}`;
                const refs = this.$refs[refName];
                const input = Array.isArray(refs) ? refs[0] : refs;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        cancelTransactionCategoryEdit: function() {
            this.editingTransactionCategoryId = null;
            this.editingTransactionCategoryValue = '';
            if (this.transactionCategoryBlurTimeout) {
                clearTimeout(this.transactionCategoryBlurTimeout);
                this.transactionCategoryBlurTimeout = null;
            }
        },
        saveTransactionCategoryEdit: async function(transaction) {
            if (!transaction || transaction.savingCategory) {
                return;
            }
            if (this.editingTransactionCategoryId !== transaction.id) {
                return;
            }

            if (this.transactionCategoryBlurTimeout) {
                clearTimeout(this.transactionCategoryBlurTimeout);
                this.transactionCategoryBlurTimeout = null;
            }

            const trimmed = (this.editingTransactionCategoryValue || '').trim();
            const currentLabel = transaction.custom_category || '';
            const isManual = transaction.custom_category_source === 'manual';
            const isFallback = transaction.custom_category_is_fallback;

            if (!trimmed && !isManual) {
                if (isFallback) {
                    this.cancelTransactionCategoryEdit();
                    return;
                }
            }

            if (trimmed && trimmed === currentLabel && isManual) {
                this.cancelTransactionCategoryEdit();
                return;
            }

            if (trimmed === currentLabel && !isManual && !isFallback) {
                this.cancelTransactionCategoryEdit();
                return;
            }

            if (trimmed && trimmed.length < 3) {
                alert('Category names must be at least 3 characters.');
                return;
            }

            transaction.savingCategory = true;
            try {
                let payload = { label: trimmed };
                if (trimmed) {
                    const match = this.customCategories.find(cat => cat.name && cat.name.toLowerCase() === trimmed.toLowerCase());
                    if (match && match.color) {
                        payload.color = match.color;
                    }
                }

                let response = await fetch(`/api/transactions/${transaction.id}/category`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                let data = await response.json();

                if (response.status === 409 && data.confirmation_required) {
                    if (confirm(data.message)) {
                        payload.force_create = true;
                        response = await fetch(`/api/transactions/${transaction.id}/category`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        data = await response.json();
                    } else {
                        this.cancelTransactionCategoryEdit();
                        return; // Exit function
                    }
                }

                if (!response.ok) {
                    throw new Error(data.error || 'Failed to update category.');
                }

                if (data.transaction) {
                    Object.assign(transaction, data.transaction);
                }
                await this.fetchCustomCategories({ force: true, suppressLoader: true, refresh: true });
                if (this.dashboardLoaded) {
                    await this.fetchDashboard({ suppressLoader: true, force: true });
                }
                this.cancelTransactionCategoryEdit();

            } catch (error) {
                console.error('Error updating transaction category:', error);
                alert(error.message || 'Failed to update category.');
            } finally {
                delete transaction.savingCategory;
            }
        },
        handleTransactionCategoryKeydown: function(event, transaction) {
            if (event.key === 'Escape') {
                event.preventDefault();
                this.cancelTransactionCategoryEdit();
            } else if (event.key === 'Enter') {
                event.preventDefault();
                this.saveTransactionCategoryEdit(transaction);
            }
        },
        handleTransactionCategoryInput: function() {
            if (this.transactionCategoryBlurTimeout) {
                clearTimeout(this.transactionCategoryBlurTimeout);
                this.transactionCategoryBlurTimeout = null;
            }
        },
        onTransactionCategoryBlur: function(transaction) {
            if (this.transactionCategoryBlurTimeout) {
                clearTimeout(this.transactionCategoryBlurTimeout);
            }
            this.transactionCategoryBlurTimeout = window.setTimeout(() => {
                this.transactionCategoryBlurTimeout = null;
                this.saveTransactionCategoryEdit(transaction);
            }, 120);
        },
        applyTransactionCategorySuggestion: function(option, transaction) {
            if (!option) {
                return;
            }
            this.editingTransactionCategoryValue = option;
            if (this.transactionCategoryBlurTimeout) {
                clearTimeout(this.transactionCategoryBlurTimeout);
                this.transactionCategoryBlurTimeout = null;
            }
            this.saveTransactionCategoryEdit(transaction);
        },
        rowSelectionStyle: function(transactionId) {
            return this.selectedTransactionIdSet.has(transactionId) ? { backgroundColor: '#bfdbfe' } : null;
        },
        toggleTransactionSelection: function(transactionId) {
            const idx = this.selectedTransactionIds.indexOf(transactionId);
            if (idx === -1) {
                this.selectedTransactionIds.push(transactionId);
            } else {
                this.selectedTransactionIds.splice(idx, 1);
            }
        },
        toggleAllDisplayedTransactionSelection: function() {
            const displayedIds = this.displayedTransactions.map(t => t.id);
            if (this.areAllDisplayedTransactionsSelected) {
                this.selectedTransactionIds = this.selectedTransactionIds.filter(id => displayedIds.indexOf(id) === -1);
            } else {
                const toAdd = displayedIds.filter(id => this.selectedTransactionIds.indexOf(id) === -1);
                this.selectedTransactionIds = this.selectedTransactionIds.concat(toAdd);
            }
        },
        clearTransactionSelection: function() {
            this.selectedTransactionIds = [];
            this.bulkCategoryValue = '';
        },
        applyBulkCategoryAssign: async function(forceCreate) {
            const trimmed = (this.bulkCategoryValue || '').trim();
            if (!trimmed) {
                alert('Please enter a category name.');
                return;
            }
            if (trimmed.length < 3) {
                alert('Category names must be at least 3 characters.');
                return;
            }
            if (!this.selectedTransactionIds.length) return;

            this.bulkCategoryApplying = true;
            try {
                const match = this.customCategories.find(cat => cat.name && cat.name.toLowerCase() === trimmed.toLowerCase());
                const payload = { transaction_ids: this.selectedTransactionIds, label: trimmed };
                if (match && match.color) payload.color = match.color;
                if (forceCreate) payload.force_create = true;

                let response = await fetch('/api/transactions/bulk-category', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                let data = await response.json();

                if (response.status === 409 && data.confirmation_required) {
                    if (confirm(data.message)) {
                        return this.applyBulkCategoryAssign(true);
                    }
                    return;
                }

                if (!response.ok) {
                    throw new Error(data.error || 'Failed to update categories.');
                }

                if (data.transactions) {
                    data.transactions.forEach(updated => {
                        const txn = this.transactions.find(t => t.id === updated.id);
                        if (txn) Object.assign(txn, updated);
                    });
                }

                await this.fetchCustomCategories({ force: true, suppressLoader: true, refresh: true });
                if (this.dashboardLoaded) {
                    await this.fetchDashboard({ suppressLoader: true, force: true });
                }
                this.clearTransactionSelection();
            } catch (error) {
                console.error('Error applying bulk category:', error);
                alert(error.message || 'Failed to update categories.');
            } finally {
                this.bulkCategoryApplying = false;
            }
        },
        applyBulkCategorySuggestion: function(option) {
            this.bulkCategoryValue = option;
        },
        buildTransactionExportUrl: function(format) {
            const params = new URLSearchParams();
            params.append('format', format);
            params.append('sort_key', this.filters.sortKey);
            params.append('sort_desc', this.filters.sortDesc ? 'true' : 'false');
            const trimmedSearch = (this.filters.search || '').trim();
            if (trimmedSearch) {
                params.append('search', trimmedSearch);
            }
            if (this.filters.startDate) {
                params.append('start_date', this.filters.startDate);
            }
            if (this.filters.endDate) {
                params.append('end_date', this.filters.endDate);
            }
            if (this.filters.amountMin !== '' && this.filters.amountMin !== null && this.filters.amountMin !== undefined) {
                params.append('min_amount', this.filters.amountMin);
            }
            if (this.filters.amountMax !== '' && this.filters.amountMax !== null && this.filters.amountMax !== undefined) {
                params.append('max_amount', this.filters.amountMax);
            }
            const customCategoryValue = (this.filters.customCategoryId || '').trim();
            if (customCategoryValue) {
                params.append('custom_category_id', customCategoryValue === '__uncategorized__' ? 'none' : customCategoryValue);
            }
            if (this.selectedAccountIds.length) {
                params.append('account_ids', this.selectedAccountIds.join(','));
            }
            return `/api/transactions/export?${params.toString()}`;
        },
        triggerTransactionExport: function(format) {
            const url = this.buildTransactionExportUrl(format);
            window.open(url, '_blank');
        },
        handleTransactionClick: function(transaction) {
            if (this.touchContextMenuTriggered) {
                this.touchContextMenuTriggered = false;
                return;
            }
            this.markAsSeen(transaction);
        },
        handleTransactionTouchStart: function(event, transaction) {
            if (!event || !transaction) {
                return;
            }
            if (!event.touches || event.touches.length !== 1) {
                return;
            }
            const touch = event.touches[0];
            const initialX = touch.clientX;
            const initialY = touch.clientY;
            this.touchContextMenuTriggered = false;
            this.touchContextMenuStart = {
                x: initialX,
                y: initialY,
                transactionId: transaction.id
            };
            if (this.touchContextMenuTimer) {
                window.clearTimeout(this.touchContextMenuTimer);
            }
            this.touchContextMenuTimer = window.setTimeout(() => {
                this.touchContextMenuTimer = null;
                const start = this.touchContextMenuStart;
                if (!start || start.transactionId !== transaction.id) {
                    return;
                }
                this.touchContextMenuTriggered = true;
                this.touchContextMenuStart = null;
                this.openTransactionMenu({ clientX: initialX, clientY: initialY }, transaction);
            }, 500);
        },
        handleTransactionTouchMove: function(event) {
            if (!this.touchContextMenuTimer || !this.touchContextMenuStart) {
                return;
            }
            if (!event.touches || event.touches.length !== 1) {
                this.handleTransactionTouchEnd();
                return;
            }
            const touch = event.touches[0];
            const dx = Math.abs(touch.clientX - this.touchContextMenuStart.x);
            const dy = Math.abs(touch.clientY - this.touchContextMenuStart.y);
            if (dx > 10 || dy > 10) {
                this.handleTransactionTouchEnd();
            }
        },
        handleTransactionTouchEnd: function() {
            if (this.touchContextMenuTimer) {
                window.clearTimeout(this.touchContextMenuTimer);
                this.touchContextMenuTimer = null;
            }
            this.touchContextMenuStart = null;
        },
        handleTransactionTouchCancel: function() {
            this.handleTransactionTouchEnd();
            this.touchContextMenuTriggered = false;
        },
        openTransactionMenu: function(event, transaction) {
            if (!transaction) {
                return;
            }
            this.closeTransactionMenu();
            this.transactionMenu.transaction = transaction;
            this.transactionMenu.visible = true;
            this.transactionMenu.x = event.clientX;
            this.transactionMenu.y = event.clientY;
            this.$nextTick(() => {
                const menu = this.$refs.transactionContextMenu;
                if (!menu || typeof menu.getBoundingClientRect !== 'function') {
                    return;
                }
                const rect = menu.getBoundingClientRect();
                const padding = 8;
                let adjustedX = this.transactionMenu.x;
                let adjustedY = this.transactionMenu.y;
                if (adjustedX + rect.width + padding > window.innerWidth) {
                    adjustedX = Math.max(padding, window.innerWidth - rect.width - padding);
                }
                if (adjustedY + rect.height + padding > window.innerHeight) {
                    adjustedY = Math.max(padding, window.innerHeight - rect.height - padding);
                }
                this.transactionMenu.x = adjustedX;
                this.transactionMenu.y = adjustedY;
            });
        },
        closeTransactionMenu: function() {
            this.transactionMenu.visible = false;
            this.transactionMenu.transaction = null;
            this.touchContextMenuTriggered = false;
        },
        handleTransactionMenuAutoCategorize: async function() {
            const contextTransaction = this.transactionMenu.transaction;
            this.closeTransactionMenu();
            if (!contextTransaction) {
                return;
            }
            const transaction = this.transactions.find(txn => txn.id === contextTransaction.id) || contextTransaction;
            if (transaction.custom_category_source === 'rule' && transaction.custom_category_id) {
                await this.focusRuleById(transaction.custom_category_id);
                return;
            }

            await this.ensureCategoriesPane();
            await this.setCategoryTab('rules');
            const description = transaction.name || '';
            const newRule = this.addCategoryRule({
                text_to_match: description,
                field_to_match: 'description',
                transaction_type: '',
                category_name: ''
            });
            this.highlightRuleRow(newRule.localId, { focusField: 'category' });
        },
        handleTransactionMenuManualOverride: function() {
            const contextTransaction = this.transactionMenu.transaction;
            this.closeTransactionMenu();
            if (!contextTransaction) {
                return;
            }
            if (this.activePane !== 'transactions') {
                this.setActivePane('transactions');
            }
            this.$nextTick(() => {
                const transaction = this.transactions.find(txn => txn.id === contextTransaction.id) || contextTransaction;
                this.startTransactionCategoryEdit(transaction);
            });
        },
        handleTransactionMenuSplit: function() {
            const contextTransaction = this.transactionMenu.transaction;
            this.closeTransactionMenu();
            if (!contextTransaction) {
                return;
            }
            let targetId = contextTransaction.id;
            if (contextTransaction.is_split_child) {
                if (!contextTransaction.parent_transaction_id) {
                    return;
                }
                targetId = contextTransaction.parent_transaction_id;
            }
            const transaction = this.transactions.find(txn => txn.id === targetId) || {
                id: targetId,
                parent_transaction_id: null,
                is_split_child: false
            };
            this.openSplitModal(transaction);
        },
        openSplitModal: async function(transaction) {
            if (!transaction) {
                return;
            }
            const targetId = transaction.is_split_child && transaction.parent_transaction_id
                ? transaction.parent_transaction_id
                : transaction.id;
            if (!targetId) {
                return;
            }
            let parentSnapshot = null;
            let fetchedChildren = [];
            try {
                const response = await fetch(`/api/transactions/${targetId}/split`);
                if (response.ok) {
                    const data = await response.json();
                    fetchedChildren = Array.isArray(data.children) ? data.children : [];
                    if (data.parent) {
                        parentSnapshot = data.parent;
                    }
                } else if (response.status === 404) {
                    alert('This transaction could not be found for splitting. It may have been removed.');
                    return;
                } else if (response.status && response.status !== 404) {
                    console.error('Failed to load split details:', response.statusText);
                }
            } catch (error) {
                console.error('Error fetching split details:', error);
            }
            if (!parentSnapshot) {
                parentSnapshot = transaction;
            }
            const parentCents = this.parseAmountToCents(parentSnapshot.amount);
            if (!Number.isFinite(parentCents) || parentCents <= 0) {
                alert('Only transactions with a non-zero amount can be split.');
                return;
            }
            if (parentCents < 2) {
                alert('This transaction amount is too small to split into multiple parts.');
                return;
            }
            let rows = [];
            if (fetchedChildren.length) {
                rows = fetchedChildren
                    .filter(child => child && child.is_split_child)
                    .map(child => {
                        const amountCents = this.parseAmountToCents(child.amount);
                        return this.createSplitRow({
                            description: child.name || '',
                            category: child.custom_category || '',
                            amountCents: Number.isFinite(amountCents) ? amountCents : 0
                        });
                    });
            }
            if (!rows.length) {
                const existingChildren = this.transactions.filter(
                    txn => txn.parent_transaction_id === parentSnapshot.id && txn.is_split_child
                );
                if (existingChildren.length) {
                    const sorted = existingChildren.slice().sort((a, b) => a.id - b.id);
                    rows = sorted.map(child => {
                        const childCents = this.parseAmountToCents(child.amount);
                        return this.createSplitRow({
                            description: child.name || '',
                            category: child.custom_category || '',
                            amountCents: Number.isFinite(childCents) ? childCents : 0
                        });
                    });
                }
            }
            if (rows.length < 2) {
                const half = Math.floor(parentCents / 2);
                const remainder = parentCents - half;
                rows = [
                    this.createSplitRow({
                        description: parentSnapshot.name || '',
                        category: '',
                        amountCents: half || parentCents
                    }),
                    this.createSplitRow({
                        description: parentSnapshot.name || '',
                        category: '',
                        amountCents: remainder
                    })
                ];
            }
            this.splitModal.visible = true;
            this.splitModal.transaction = parentSnapshot;
            this.splitModal.parentAmountCents = parentCents;
            this.splitModal.rows = rows;
            this.splitModal.errors = [];
            this.splitModal.saving = false;
            this.closeSplitCategoryDropdown();
            document.body.classList.add('modal-open');
            this.$nextTick(() => {
                this.recalculateSplitAutoAmounts();
                this.updateSplitValidation();
                const firstRowRef = this.$refs[`splitDescription-${rows[0].id}`];
                const input = Array.isArray(firstRowRef) ? firstRowRef[0] : firstRowRef;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        closeSplitModal: function() {
            this.splitModal.visible = false;
            this.splitModal.transaction = null;
            this.splitModal.rows = [];
            this.splitModal.errors = [];
            this.splitModal.parentAmountCents = 0;
            this.splitModal.saving = false;
            this.closeSplitCategoryDropdown();
            document.body.classList.remove('modal-open');
        },
        createSplitRow: function(initial = {}) {
            const id = `split-${Date.now()}-${++this.nextSplitRowId}`;
            let amountValue = '0.00';
            if (typeof initial.amountCents === 'number') {
                amountValue = this.formatCentsToAmount(initial.amountCents);
            } else if (typeof initial.amount === 'string' || typeof initial.amount === 'number') {
                const cents = this.parseAmountToCents(initial.amount);
                amountValue = this.formatCentsToAmount(Number.isFinite(cents) ? cents : 0);
            }
            return {
                id,
                description: initial.description || '',
                category: initial.category || '',
                amount: amountValue
            };
        },
        recalculateSplitAutoAmounts: function() {
            if (!this.splitModal.rows.length) {
                return;
            }
            const parentCents = this.splitModal.parentAmountCents || 0;
            const lastIndex = this.splitModal.rows.length - 1;
            let used = 0;
            this.splitModal.rows.forEach((row, index) => {
                if (index === lastIndex) {
                    return;
                }
                const cents = this.parseAmountToCents(row.amount);
                if (cents !== null) {
                    used += cents;
                }
            });
            const remaining = parentCents - used;
            const lastRow = this.splitModal.rows[lastIndex];
            if (lastRow) {
                lastRow.amount = this.formatCentsToAmount(remaining >= 0 ? remaining : 0);
            }
        },
        parseAmountToCents: function(value) {
            if (value === null || value === undefined || value === '') {
                return null;
            }
            const numeric = Number(String(value).replace(/[^0-9.\-]/g, ''));
            if (!Number.isFinite(numeric)) {
                return null;
            }
            return Math.round(Math.abs(numeric) * 100);
        },
        formatCentsToAmount: function(cents) {
            if (!Number.isFinite(cents)) {
                return '0.00';
            }
            return (Math.max(0, cents) / 100).toFixed(2);
        },
        updateSplitValidation: function() {
            if (!this.splitModal.visible) {
                this.splitModal.errors = [];
                return true;
            }
            const errors = [];
            const rows = this.splitModal.rows;
            const parentCents = this.splitModal.parentAmountCents || 0;
            const parentTransaction = this.splitModal.transaction || {};
            const fallbackSegments = Array.isArray(parentTransaction.category)
                ? parentTransaction.category.filter(item => !!item)
                : [];
            const fallbackLabel = fallbackSegments.length ? fallbackSegments.join(' / ') : '';
            const fallbackLabelLower = fallbackLabel.toLowerCase();
            const fallbackSegmentSet = new Set(fallbackSegments.map(item => item.toLowerCase()));
            if (rows.length < 2) {
                errors.push('Provide at least two split rows.');
            }
            const categorySet = new Set();
            let totalCents = 0;
            rows.forEach((row, index) => {
                const desc = (row.description || '').trim();
                const category = (row.category || '').trim();
                if (!desc) {
                    errors.push(`Row ${index + 1}: Description is required.`);
                }
                if (!category) {
                    errors.push(`Row ${index + 1}: Category is required.`);
                } else {
                    if (category.length < 3) {
                        errors.push(`Row ${index + 1}: Category must be at least 3 characters.`);
                    }
                    const key = category.toLowerCase();
                    if (categorySet.has(key)) {
                        errors.push('Split categories must be unique.');
                    } else {
                        categorySet.add(key);
                    }
                    if (fallbackSegmentSet.has(key) || (!!fallbackLabel && key === fallbackLabelLower)) {
                        errors.push(`Row ${index + 1}: Category cannot match the original Automatic category.`);
                    }
                }
                const cents = this.parseAmountToCents(row.amount);
                if (cents === null || cents <= 0) {
                    errors.push(`Row ${index + 1}: Amount must be greater than zero.`);
                } else {
                    totalCents += cents;
                }
            });
            const diff = parentCents - totalCents;
            if (diff !== 0) {
                errors.push('Split amounts must total the transaction amount.');
            }
            this.splitModal.errors = Array.from(new Set(errors));
            return this.splitModal.errors.length === 0;
        },
        handleSplitAmountInput: function() {
            if (!this.splitModal.visible) {
                return;
            }
            this.recalculateSplitAutoAmounts();
            this.updateSplitValidation();
        },
        handleSplitFieldInput: function() {
            if (!this.splitModal.visible) {
                return;
            }
            this.updateSplitValidation();
        },
        openSplitCategoryDropdown: function(row) {
            if (!row) {
                return;
            }
            this.splitCategoryDropdown.rowId = row.id;
            this.updateSplitCategorySuggestions(row);
        },
        handleSplitCategoryInput: function(row) {
            if (!row) {
                return;
            }
            this.openSplitCategoryDropdown(row);
            this.handleSplitFieldInput();
        },
        updateSplitCategorySuggestions: function(row) {
            const options = this.splitCategoryOptions || [];
            let items = options;
            const query = (row.category || '').trim().toLowerCase();
            if (query) {
                items = options.filter(option => option.toLowerCase().includes(query));
            }
            this.splitCategoryDropdown.items = items.slice(0, 8);
        },
        applySplitCategorySuggestion: function(option, row) {
            if (!option || !row) {
                return;
            }
            row.category = option;
            this.handleSplitFieldInput();
            this.closeSplitCategoryDropdown();
            this.$nextTick(() => {
                const ref = this.$refs[`splitCategoryInput-${row.id}`];
                const input = Array.isArray(ref) ? ref[0] : ref;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        closeSplitCategoryDropdown: function() {
            this.splitCategoryDropdown.rowId = null;
            this.splitCategoryDropdown.items = [];
            if (this.splitCategoryBlurTimeout) {
                window.clearTimeout(this.splitCategoryBlurTimeout);
                this.splitCategoryBlurTimeout = null;
            }
        },
        onSplitCategoryBlur: function() {
            if (this.splitCategoryBlurTimeout) {
                window.clearTimeout(this.splitCategoryBlurTimeout);
            }
            this.splitCategoryBlurTimeout = window.setTimeout(() => {
                this.closeSplitCategoryDropdown();
            }, 120);
        },
        addSplitRow: function() {
            if (!this.splitModal.visible) {
                return;
            }
            const insertionIndex = Math.max(this.splitModal.rows.length - 1, 0);
            const newRow = this.createSplitRow();
            this.splitModal.rows.splice(insertionIndex, 0, newRow);
            this.$nextTick(() => {
                this.recalculateSplitAutoAmounts();
                this.updateSplitValidation();
                const ref = this.$refs[`splitDescription-${newRow.id}`];
                const input = Array.isArray(ref) ? ref[0] : ref;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        removeSplitRow: function(index) {
            if (!this.splitModal.visible) {
                return;
            }
            if (this.splitModal.rows.length <= 2) {
                return;
            }
            const focusIndex = Math.min(index, this.splitModal.rows.length - 2);
            const focusRow = this.splitModal.rows[focusIndex];
            this.splitModal.rows.splice(index, 1);
            this.$nextTick(() => {
                this.recalculateSplitAutoAmounts();
                this.updateSplitValidation();
                if (focusRow) {
                    const ref = this.$refs[`splitDescription-${focusRow.id}`];
                    const input = Array.isArray(ref) ? ref[0] : ref;
                    if (input && typeof input.focus === 'function') {
                        input.focus();
                    }
                }
            });
        },
        submitSplitModal: async function() {
            if (!this.splitModal.visible || this.splitModal.saving) {
                return;
            }
            this.recalculateSplitAutoAmounts();
            if (!this.updateSplitValidation()) {
                return;
            }
            const transaction = this.splitModal.transaction;
            if (!transaction) {
                return;
            }
            this.splitModal.saving = true;
            try {
                const payload = {
                    splits: this.splitModal.rows.map(row => ({
                        description: (row.description || '').trim(),
                        category: (row.category || '').trim(),
                        amount: row.amount
                    }))
                };
                const response = await fetch(`/api/transactions/${transaction.id}/split`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!response.ok) {
                    const message = data && data.error ? data.error : 'Failed to split transaction.';
                    this.splitModal.errors = [message];
                    return;
                }
                this.closeSplitModal();
                await this.fetchTransactions({ reset: false, skipLoadingState: true });
                await this.fetchCustomCategories({ force: true, suppressLoader: true, refresh: true });
                if (this.dashboardLoaded) {
                    await this.fetchDashboard({ suppressLoader: true, force: true });
                }
            } catch (error) {
                console.error('Error splitting transaction:', error);
                this.splitModal.errors = [error.message || 'Failed to split transaction.'];
            } finally {
                this.splitModal.saving = false;
            }
        },
        ensureCategoriesPane: async function() {
            if (this.activePane !== 'categories') {
                await this.setActivePane('categories');
            } else {
                if (!this.customCategoriesLoaded && !this.customCategoriesLoading) {
                    await this.fetchCustomCategories();
                }
                if (!this.categoriesLoaded && !this.categoriesLoading) {
                    await this.fetchCategoryRules();
                }
            }
        },
        focusRuleById: async function(ruleId) {
            if (!ruleId) {
                return;
            }
            await this.ensureCategoriesPane();
            await this.setCategoryTab('rules');
            const rule = this.categoryRules.find(item => item.id === ruleId);
            if (rule) {
                this.highlightRuleRow(rule.localId);
            }
        },
        highlightRuleRow: function(localId, options = {}) {
            if (!localId) {
                return;
            }
            if (this.highlightedRuleTimeout) {
                window.clearTimeout(this.highlightedRuleTimeout);
                this.highlightedRuleTimeout = null;
            }
            this.highlightedRuleLocalId = localId;
            const duration = typeof options.duration === 'number' ? options.duration : 2600;
            this.$nextTick(() => {
                const rowRefName = `categoryRuleRow-${localId}`;
                const rowRefs = this.$refs[rowRefName];
                const row = Array.isArray(rowRefs) ? rowRefs[0] : rowRefs;
                if (row && typeof row.scrollIntoView === 'function') {
                    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                if (options.focusField) {
                    this.focusRuleInput(localId, options.focusField);
                }
            });
            if (duration > 0) {
                this.highlightedRuleTimeout = window.setTimeout(() => {
                    this.highlightedRuleLocalId = null;
                    this.highlightedRuleTimeout = null;
                }, duration);
            }
        },
        highlightCategoryRow: function(localId, options = {}) {
            if (!localId) {
                return;
            }
            if (this.highlightedCategoryTimeout) {
                window.clearTimeout(this.highlightedCategoryTimeout);
                this.highlightedCategoryTimeout = null;
            }
            this.highlightedCategoryLocalId = localId;
            const duration = typeof options.duration === 'number' ? options.duration : 2600;
            this.$nextTick(() => {
                const refName = `customCategoryRow-${localId}`;
                const refs = this.$refs[refName];
                const row = Array.isArray(refs) ? refs[0] : refs;
                if (row && typeof row.scrollIntoView === 'function') {
                    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            });
            if (duration > 0) {
                this.highlightedCategoryTimeout = window.setTimeout(() => {
                    this.highlightedCategoryLocalId = null;
                    this.highlightedCategoryTimeout = null;
                }, duration);
            }
        },
        highlightCustomCategory: function(name) {
            const target = (name || '').trim().toLowerCase();
            if (!target) {
                return;
            }
            const match = this.customCategories.find(category => category && category.name && category.name.trim().toLowerCase() === target);
            if (!match) {
                return;
            }
            const localId = match.localId;
            this.$nextTick(() => {
                this.highlightCategoryRow(localId);
            });
        },
        focusCustomCategoryByName: async function(name) {
            const trimmed = (name || '').trim();
            if (!trimmed) {
                return;
            }
            if (this.categoryTab !== 'manage') {
                await this.setCategoryTab('manage');
            }
            if (!this.customCategoriesLoaded && !this.customCategoriesLoading) {
                await this.fetchCustomCategories({ force: true, suppressLoader: true });
            }
            await this.$nextTick();
            this.highlightCustomCategory(trimmed);
        },
        focusRuleInput: function(localId, target) {
            if (!localId || !target) {
                return;
            }
            const refName = target === 'category' ? `ruleCategoryInput-${localId}` : `ruleTextInput-${localId}`;
            const refs = this.$refs[refName];
            const input = Array.isArray(refs) ? refs[0] : refs;
            if (input && typeof input.focus === 'function') {
                input.focus();
                if (target === 'text' && typeof input.select === 'function') {
                    input.select();
                }
            }
        },
        handleRuleInputBlur: function(rule) {
            if (!rule) {
                return;
            }
            window.setTimeout(() => {
                const rowRefName = `categoryRuleRow-${rule.localId}`;
                const rowRefs = this.$refs[rowRefName];
                const row = Array.isArray(rowRefs) ? rowRefs[0] : rowRefs;
                const active = document.activeElement;
                if (row && active && row.contains(active)) {
                    return;
                }
                this.discardRuleIfEmpty(rule);
            }, 0);
        },
        discardRuleIfEmpty: function(rule) {
            if (!rule) {
                return;
            }
            const draftText = rule.draft ? (rule.draft.text_to_match || '').trim() : '';
            const draftCategory = rule.draft ? (rule.draft.category_name || '').trim() : '';
            const text = (rule.text_to_match || '').trim() || draftText;
            const categoryName = (rule.category_name || '').trim() || draftCategory;
            if (text && categoryName) {
                return;
            }
            if (rule.isNew) {
                this.categoryRules = this.categoryRules.filter(item => item.localId !== rule.localId);
                if (this.highlightedRuleLocalId === rule.localId) {
                    this.highlightedRuleLocalId = null;
                }
                this.categoriesError = null;
                this.updateCategoryLabels();
            }
        },
        createBudgetRow: function(initial = {}) {
            const localId = initial.id ? `budget-${initial.id}` : `budget-${Date.now()}-${++this.nextBudgetTempId}`;
            return {
                id: initial.id || null,
                localId: localId,
                category_label: initial.category_label || '',
                frequency: initial.frequency || 'monthly',
                amount: this.normalizeBudgetAmount(initial.amount),
                sixMonthAverage: Number(initial.six_month_average || initial.sixMonthAverage || 0),
                currentMonthTotal: Number(initial.current_month_total || initial.currentMonthTotal || 0),
                classification: initial.classification || 'expense',
                isDirty: Boolean(initial.isDirty),
                isNew: !initial.id,
                saving: false
            };
        },
        normalizeBudgetAmount: function(value) {
            const numeric = Number.parseFloat(value);
            if (!Number.isFinite(numeric)) {
                return '0.00';
            }
            return numeric.toFixed(2);
        },
        updateBudgetSummary: function(summary) {
            if (!summary) {
                this.budgetSummary = { income_total: 0, expense_total: 0, net_total: 0 };
                return;
            }
            this.budgetSummary = {
                income_total: Number(summary.income_total || 0),
                expense_total: Number(summary.expense_total || 0),
                net_total: Number(summary.net_total || 0)
            };
        },
        fetchBudgets: async function(options = {}) {
            const { suppressLoader = false, force = false } = options;
            if (this.budgetsLoading) {
                return;
            }
            if (this.budgetsLoaded && !force && !options.refreshOnly) {
                return;
            }
            if (!suppressLoader) {
                this.budgetsLoading = true;
            }
            this.budgetsError = null;
            try {
                const response = await fetch('/api/budgets');
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to load budgets.');
                }
                const rows = Array.isArray(data.budgets) ? data.budgets : [];
                this.budgets = rows.map(raw => this.createBudgetRow(raw));
                this.updateBudgetSummary(data.summary);
                this.budgetsLoaded = true;
            } catch (error) {
                console.error('Error fetching budgets:', error);
                this.budgetsError = error.message || 'Failed to load budgets.';
            } finally {
                if (!suppressLoader) {
                    this.budgetsLoading = false;
                }
            }
        },
        addBudgetRow: function() {
            const newRow = this.createBudgetRow({
                category_label: '',
                frequency: 'monthly',
                amount: '0.00',
                isDirty: true
            });
            newRow.isNew = true;
            this.budgets.unshift(newRow);
            this.budgetsError = null;
            this.budgetsLoaded = true;
            this.markBudgetDirty(newRow);
            this.$nextTick(() => {
                const ref = this.$refs[`budgetCategorySelect-${newRow.localId}`];
                const el = Array.isArray(ref) ? ref[0] : ref;
                if (el && typeof el.focus === 'function') {
                    el.focus();
                }
            });
        },
        markBudgetDirty: function(budget) {
            if (!budget) {
                return;
            }
            budget.isDirty = true;
            this.budgetsError = null;
            this.cancelBudgetBlur();
        },
        saveBudgetRow: async function(budget) {
            if (!budget || budget.saving) {
                return;
            }
            const category = (budget.category_label || '').trim();
            if (!category) {
                this.budgetsError = 'Category is required.';
                return;
            }
            const amountValue = Number.parseFloat(budget.amount);
            if (!Number.isFinite(amountValue) || amountValue <= 0) {
                this.budgetsError = 'Amount must be greater than zero.';
                return;
            }
            budget.saving = true;
            this.budgetsError = null;
            try {
                const payload = {
                    category_label: category,
                    frequency: budget.frequency,
                    amount: this.normalizeBudgetAmount(budget.amount)
                };
                const url = budget.id ? `/api/budgets/${budget.id}` : '/api/budgets';
                const method = budget.id ? 'PUT' : 'POST';
                const response = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to save budget.');
                }
                if (data.budget) {
                    const updated = this.createBudgetRow(data.budget);
                    Object.assign(budget, updated, { isDirty: false, isNew: false, saving: false });
                }
                if (data.summary) {
                    this.updateBudgetSummary(data.summary);
                }
                this.budgetsLoaded = true;
                if (data.budgets) {
                    this.budgets = data.budgets.map(raw => this.createBudgetRow(raw));
                    this.budgetsLoaded = true;
                }
                this.closeBudgetCategoryDropdown();
            } catch (error) {
                console.error('Error saving budget:', error);
                this.budgetsError = error.message || 'Failed to save budget.';
            } finally {
                budget.saving = false;
            }
        },
        deleteBudgetRow: async function(budget) {
            if (!budget) {
                return;
            }
            if (!budget.id) {
                this.budgets = this.budgets.filter(item => item.localId !== budget.localId);
                if (this.budgetCategoryDropdown.rowId === budget.localId) {
                    this.closeBudgetCategoryDropdown();
                }
                this.cancelBudgetBlur();
                return;
            }
            if (!window.confirm('Delete this budget entry?')) {
                return;
            }
            budget.saving = true;
            try {
                const response = await fetch(`/api/budgets/${budget.id}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to delete budget.');
                }
                if (data.budgets) {
                    this.budgets = data.budgets.map(raw => this.createBudgetRow(raw));
                    this.budgetsLoaded = true;
                } else {
                    this.budgets = this.budgets.filter(item => item.localId !== budget.localId);
                }
                if (data.summary) {
                    this.updateBudgetSummary(data.summary);
                }
                this.closeBudgetCategoryDropdown();
                this.cancelBudgetBlur();
            } catch (error) {
                console.error('Error deleting budget:', error);
                this.budgetsError = error.message || 'Failed to delete budget.';
            } finally {
                budget.saving = false;
            }
        },
        openBudgetCategoryDropdown: function(budget) {
            if (!budget) {
                return;
            }
            this.budgetCategoryDropdown.rowId = budget.localId;
            this.updateBudgetCategorySuggestions(budget);
        },
        handleBudgetCategoryInput: function(budget) {
            if (!budget) {
                return;
            }
            this.openBudgetCategoryDropdown(budget);
            this.markBudgetDirty(budget);
            this.cancelBudgetBlur();
        },
        updateBudgetCategorySuggestions: function(budget) {
            // Existing budgets have a fixed category — no dropdown needed.
            if (budget.id) {
                this.budgetCategoryDropdown.items = [];
                return;
            }
            const options = this.availableBudgetCategories || [];
            const query = (budget.category_label || '').trim().toLowerCase();
            const items = query
                ? options.filter(option => option.toLowerCase().includes(query))
                : options;
            this.budgetCategoryDropdown.items = items;
            this.cancelBudgetBlur();
        },
        applyBudgetCategorySuggestion: function(option, budget) {
            if (!option || !budget) {
                return;
            }
            budget.category_label = option;
            this.markBudgetDirty(budget);
            this.closeBudgetCategoryDropdown();
            this.$nextTick(() => {
                const ref = this.$refs[`budgetCategoryInput-${budget.localId}`];
                const input = Array.isArray(ref) ? ref[0] : ref;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        closeBudgetCategoryDropdown: function() {
            this.budgetCategoryDropdown.rowId = null;
            this.budgetCategoryDropdown.items = [];
            if (this.budgetCategoryBlurTimeout) {
                window.clearTimeout(this.budgetCategoryBlurTimeout);
                this.budgetCategoryBlurTimeout = null;
            }
        },
        onBudgetCategoryBlur: function() {
            if (this.budgetCategoryBlurTimeout) {
                window.clearTimeout(this.budgetCategoryBlurTimeout);
            }
            this.budgetCategoryBlurTimeout = window.setTimeout(() => {
                this.closeBudgetCategoryDropdown();
            }, 120);
        },
        cancelBudgetBlur: function() {
            if (this.budgetCategoryBlurTimeout) {
                window.clearTimeout(this.budgetCategoryBlurTimeout);
                this.budgetCategoryBlurTimeout = null;
            }
        },
        discardBudgetRowIfEmpty: function() {
            const removableIds = new Set();
            this.budgets.forEach(budget => {
                if (budget.id) {
                    return;
                }
                const category = (budget.category_label || '').trim();
                const amountValue = Number.parseFloat(budget.amount);
                if (!category || !Number.isFinite(amountValue) || amountValue <= 0) {
                    removableIds.add(budget.localId);
                }
            });
            if (!removableIds.size) {
                return;
            }
            this.budgets = this.budgets.filter(budget => !removableIds.has(budget.localId));
            if (removableIds.has(this.budgetCategoryDropdown.rowId)) {
                this.closeBudgetCategoryDropdown();
            }
        },
        sortCustomCategories: function() {
            this.customCategories.sort((a, b) => {
                const nameA = (a && a.name ? a.name : '').trim().toLowerCase();
                const nameB = (b && b.name ? b.name : '').trim().toLowerCase();
                if (nameA === nameB) {
                    const idA = a && (a.id || a.localId) ? String(a.id || a.localId) : '';
                    const idB = b && (b.id || b.localId) ? String(b.id || b.localId) : '';
                    return idA.localeCompare(idB);
                }
                if (!nameA) {
                    return 1;
                }
                if (!nameB) {
                    return -1;
                }
                return nameA.localeCompare(nameB);
            });
        },
        fetchCustomCategories: async function(options = {}) {
            const { force = false, suppressLoader = false } = options;
            if (this.customCategoriesLoading) {
                return;
            }
            if (!force && this.customCategoriesLoaded && !options.refresh) {
                return;
            }

            if (!suppressLoader) {
                this.customCategoriesLoading = true;
            }
            this.customCategoriesError = null;

            try {
                const response = await fetch('/api/custom-categories');
                if (!response.ok) {
                    throw new Error('Failed to load custom categories.');
                }
                const data = await response.json();
                this.customCategories = (data.categories || []).map(cat => this.prepareCustomCategory(cat));
                this.sortCustomCategories();
                this.customCategoriesLoaded = true;
                this.updateCategoryLabels(data.labels);
            } catch (error) {
                console.error('Error fetching custom categories:', error);
                this.customCategoriesError = error.message || 'Failed to load custom categories.';
            } finally {
                this.customCategoriesLoading = false;
            }
        },
        fetchCategoryRules: async function(options = {}) {
            const { force = false, suppressLoader = false } = options;
            if (this.categoriesLoading) {
                return;
            }
            if (!force && this.categoriesLoaded) {
                const hasDirty = this.categoryRules.some(rule => rule.isDirty && !rule.saving);
                if (hasDirty) {
                    return;
                }
                if (!options.refresh) {
                    return;
                }
            }

            if (!suppressLoader) {
                this.categoriesLoading = true;
            }
            this.categoriesError = null;

            try {
                const response = await fetch('/api/categories');
                if (!response.ok) {
                    throw new Error('Failed to load category rules.');
                }
                const data = await response.json();
                this.categoryRules = (data.categories || []).map(rule => this.prepareCategoryRule(rule));
                this.categoriesLoaded = true;
                if (data.labels) {
                    this.updateCategoryLabels(data.labels);
                } else {
                    this.updateCategoryLabels();
                }
                this.categoryRules.forEach(rule => this.resetRuleDraft(rule));
            } catch (error) {
                console.error('Error fetching category rules:', error);
                this.categoriesError = error.message || 'Failed to load category rules.';
            } finally {
                this.categoriesLoading = false;
            }
        },
        fetchCategories: async function(options = {}) {
            await this.fetchCustomCategories(options);
            await this.fetchCategoryRules(options);
        },
        prepareCustomCategory: function(raw) {
            const categoryId = raw.id || null;
            const normalizedColor = this.normalizeColor(raw.color);
            return {
                id: categoryId,
                localId: categoryId ? `cat-${categoryId}` : `local-cat-${Date.now()}-${++this.nextCustomCategoryTempId}`,
                name: raw.name || '',
                color: normalizedColor,
                rule_count: Number.isFinite(raw.rule_count) ? raw.rule_count : 0,
                transaction_count: Number.isFinite(raw.transaction_count) ? raw.transaction_count : 0,
                override_count: Number.isFinite(raw.override_count) ? raw.override_count : 0,
                isDirty: false,
                isNew: !categoryId,
                saving: false,
                isEditing: false,
                editableName: raw.name || '',
                editableColor: normalizedColor
            };
        },
        prepareCategoryRule: function(raw) {
            const ruleId = raw.id || null;
            const categoryInfo = raw.category || {};
            const categoryId = raw.category_id || categoryInfo.id || null;
            const categoryName = categoryInfo.name || '';
            const categoryColor = this.normalizeColor(categoryInfo.color);
            return {
                id: ruleId,
                localId: ruleId ? `rule-${ruleId}` : `local-${Date.now()}-${++this.nextCategoryTempId}`,
                text_to_match: raw.text_to_match || '',
                field_to_match: raw.field_to_match || 'description',
                transaction_type: raw.transaction_type || '',
                amount_min: raw.amount_min !== null && raw.amount_min !== undefined ? String(raw.amount_min) : '',
                amount_max: raw.amount_max !== null && raw.amount_max !== undefined ? String(raw.amount_max) : '',
                category_id: categoryId,
                category_name: categoryName,
                category_color: categoryColor,
                isDirty: false,
                isNew: false,
                saving: false,
                isEditing: false,
                draft: null
            };
        },
        addCategoryRule: function(initial = {}) {
            const tempId = `new-${Date.now()}-${++this.nextCategoryTempId}`;
            const initialColor = initial.category_color ? this.normalizeColor(initial.category_color) : this.categoryPalette[0];
            const newRule = {
                id: null,
                localId: tempId,
                text_to_match: initial.text_to_match || '',
                field_to_match: initial.field_to_match || 'description',
                transaction_type: initial.transaction_type || '',
                amount_min: initial.amount_min || '',
                amount_max: initial.amount_max || '',
                category_id: initial.category_id || null,
                category_name: initial.category_name || '',
                category_color: initialColor,
                isDirty: initial.isDirty !== undefined ? initial.isDirty : true,
                isNew: true,
                saving: false,
                isEditing: true,
                draft: null
            };
            this.categoryRules.unshift(newRule);
            this.categoriesLoaded = true;
            this.categoriesError = null;
            this.updateCategoryLabels();
            this.resetRuleDraft(newRule);
            if (newRule.isNew && newRule.draft) {
                const hasText = (newRule.draft.text_to_match || '').trim().length > 0;
                newRule.isDirty = hasText;
            }
            this.highlightRuleRow(newRule.localId, { focusField: 'text' });
            return newRule;
        },
        addCustomCategory: function(initial = {}) {
            const tempId = `cat-new-${Date.now()}-${++this.nextCustomCategoryTempId}`;
            const newCategory = {
                id: null,
                localId: tempId,
                name: initial.name || '',
                color: initial.color ? this.normalizeColor(initial.color) : this.categoryPalette[0],
                rule_count: 0,
                transaction_count: 0,
                override_count: 0,
                isDirty: initial.isDirty !== undefined ? initial.isDirty : true,
                isNew: true,
                saving: false,
                isEditing: true,
                editableName: initial.name || '',
                editableColor: initial.color ? this.normalizeColor(initial.color) : this.categoryPalette[0]
            };
            this.customCategories.unshift(newCategory);
            this.customCategoriesLoaded = true;
            this.customCategoriesError = null;
            this.updateCategoryLabels();
            this.$nextTick(() => {
                const ref = this.$refs[`categoryNameInput-${newCategory.localId}`];
                const input = Array.isArray(ref) ? ref[0] : ref;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                }
            });
            return newCategory;
        },
        markCustomCategoryDirty: function(category) {
            if (!category) {
                return;
            }
            category.isDirty = true;
            this.customCategoriesError = null;
        },
        saveCustomCategory: async function(category) {
            if (!category || category.saving) {
                return;
            }
            const name = (category.editableName || category.name || '').trim();
            if (!name) {
                this.customCategoriesError = 'Category name is required.';
                return;
            }
            if (name.length < 3) {
                this.customCategoriesError = 'Category name must be at least 3 characters.';
                return;
            }
            const payload = {
                name,
                color: this.normalizeColor(category.editableColor || category.color)
            };

            const url = category.id ? `/api/custom-categories/${category.id}` : '/api/custom-categories';
            const method = category.id ? 'PUT' : 'POST';

            category.saving = true;
            try {
                const response = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to save category.');
                }
                const updated = data.category || {};
                const prepared = this.prepareCustomCategory(updated);
                category.id = prepared.id;
                category.localId = prepared.localId;
                category.name = prepared.name;
                category.color = prepared.color;
                category.editableName = prepared.name;
                category.editableColor = prepared.color;
                category.rule_count = prepared.rule_count;
                category.transaction_count = prepared.transaction_count;
                category.override_count = prepared.override_count;
                category.isDirty = false;
                category.isNew = false;
                category.isEditing = false;
                if (this.openCategoryColorId === category.localId) {
                    this.openCategoryColorId = null;
                }
                this.sortCustomCategories();
                this.customCategoriesError = null;
                this.updateCategoryLabels(data.labels);
                this.categoryRules.forEach(rule => {
                    if (rule.category_id === category.id) {
                        rule.category_name = category.name;
                        rule.category_color = category.color;
                        rule.isDirty = false;
                        this.resetRuleDraft(rule);
                    }
                });
                await this.fetchTransactions({ reset: false, skipLoadingState: true });
                await this.fetchCategoryRules({ force: true, suppressLoader: true, refresh: true });
                if (this.dashboardLoaded) {
                    await this.fetchDashboard({ suppressLoader: true, force: true });
                }
            } catch (error) {
                console.error('Error saving custom category:', error);
                this.customCategoriesError = error.message || 'Failed to save category.';
            } finally {
                category.saving = false;
            }
        },
        deleteCustomCategory: async function(category) {
            if (!category || category.saving) {
                return;
            }

            if (!category.id) {
                if (this.openCategoryColorId === category.localId) {
                    this.openCategoryColorId = null;
                }
                this.customCategories = this.customCategories.filter(item => item.localId !== category.localId);
                this.sortCustomCategories();
                this.updateCategoryLabels();
                this.customCategoriesError = null;
                return;
            }

            if (!window.confirm('Delete this custom category and associated rules?')) {
                return;
            }

            category.saving = true;
            try {
                const response = await fetch(`/api/custom-categories/${category.id}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to delete category.');
                }
                if (this.openCategoryColorId === category.localId) {
                    this.openCategoryColorId = null;
                }
                this.customCategories = this.customCategories.filter(item => item.localId !== category.localId);
                this.sortCustomCategories();
                this.customCategoriesError = null;
                this.updateCategoryLabels(data.labels);
                await this.fetchCategoryRules({ force: true, suppressLoader: true, refresh: true });
                await this.fetchTransactions({ reset: true, skipLoadingState: true });
                if (this.dashboardLoaded) {
                    await this.fetchDashboard({ suppressLoader: true, force: true });
                }
            } catch (error) {
                console.error('Error deleting custom category:', error);
                this.customCategoriesError = error.message || 'Failed to delete category.';
            } finally {
                category.saving = false;
            }
        },
        startCustomCategoryEdit: function(category) {
            if (!category || category.saving) {
                return;
            }
            category.editableName = category.name || '';
            category.editableColor = this.normalizeColor(category.color);
            category.isEditing = true;
            category.isDirty = false;
            this.customCategoriesError = null;
            this.$nextTick(() => {
                const ref = this.$refs[`categoryNameInput-${category.localId}`];
                const input = Array.isArray(ref) ? ref[0] : ref;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        cancelCustomCategoryEdit: function(category) {
            if (!category) {
                return;
            }
            if (!category.id && category.isNew) {
                this.customCategories = this.customCategories.filter(item => item.localId !== category.localId);
                return;
            }
            category.editableName = category.name || '';
            category.editableColor = this.normalizeColor(category.color);
            category.isEditing = false;
            category.isDirty = false;
            this.customCategoriesError = null;
            if (this.openCategoryColorId === category.localId) {
                this.openCategoryColorId = null;
            }
        },
        createRuleDraft: function(rule) {
            return {
                text_to_match: rule.text_to_match || '',
                field_to_match: rule.field_to_match || 'description',
                transaction_type: rule.transaction_type || '',
                amount_min: rule.amount_min !== null && rule.amount_min !== undefined ? String(rule.amount_min) : '',
                amount_max: rule.amount_max !== null && rule.amount_max !== undefined ? String(rule.amount_max) : '',
                category_id: rule.category_id || null,
                category_name: rule.category_name || '',
                category_color: this.normalizeColor(rule.category_color)
            };
        },
        resetRuleDraft: function(rule) {
            if (!rule) {
                return;
            }
            rule.draft = this.createRuleDraft(rule);
            rule.isDirty = false;
        },
        startRuleEdit: function(rule) {
            if (!rule || rule.saving) {
                return;
            }
            this.resetRuleDraft(rule);
            rule.isEditing = true;
            this.categoriesError = null;
            this.highlightRuleRow(rule.localId);
            this.$nextTick(() => {
                const ref = this.$refs[`ruleTextInput-${rule.localId}`];
                const input = Array.isArray(ref) ? ref[0] : ref;
                if (input && typeof input.focus === 'function') {
                    input.focus();
                    input.select();
                }
            });
        },
        cancelRuleEdit: function(rule) {
            if (!rule) {
                return;
            }
            if (!rule.id && rule.isNew) {
                this.categoryRules = this.categoryRules.filter(item => item.localId !== rule.localId);
                this.updateCategoryLabels();
                return;
            }
            this.resetRuleDraft(rule);
            rule.isEditing = false;
            this.categoriesError = null;
        },
        markRuleDraftDirty: function(rule) {
            if (!rule) {
                return;
            }
            if (!rule.isEditing && !rule.isNew) {
                return;
            }
            rule.isDirty = true;
            this.categoriesError = null;
        },
        markRuleDirty: function(rule) {
            this.markRuleDraftDirty(rule);
        },
        handleRuleCategoryInput: function(rule) {
            if (!rule) {
                return;
            }
            const draft = rule.draft || this.createRuleDraft(rule);
            const name = (draft.category_name || '').trim().toLowerCase();
            if (name) {
                const match = this.customCategories.find(cat => cat.name && cat.name.toLowerCase() === name);
                if (match) {
                    draft.category_id = match.id;
                    draft.category_name = match.name;
                    draft.category_color = match.color;
                } else {
                    draft.category_id = null;
                    draft.category_color = this.normalizeColor(this.categoryPalette[0]);
                }
            } else {
                draft.category_id = null;
                draft.category_color = this.normalizeColor(this.categoryPalette[0]);
            }
            this.markRuleDraftDirty(rule);
        },
        saveCategoryRule: async function(rule) {
            if (!rule || rule.saving) {
                return;
            }
            if (!rule.isEditing && !rule.isNew) {
                this.startRuleEdit(rule);
                return;
            }
            const draft = rule.draft || this.createRuleDraft(rule);
            const text = (draft.text_to_match || '').trim();
            let categoryName = (draft.category_name || '').trim();
            let categoryId = draft.category_id;
            if (!categoryId && categoryName) {
                const match = this.customCategories.find(cat => cat.name && cat.name.toLowerCase() === categoryName.toLowerCase());
                if (match) {
                    categoryId = match.id;
                    draft.category_id = match.id;
                    draft.category_color = match.color;
                    categoryName = match.name;
                }
            }
            if (!text) {
                this.categoriesError = '"Text to match" is required.';
                return;
            }
            if (!categoryId && !categoryName) {
                this.categoriesError = 'Select or enter a custom category.';
                return;
            }

            const payload = {
                text_to_match: text,
                field_to_match: draft.field_to_match || 'description',
                transaction_type: draft.transaction_type || null,
                amount_min: draft.amount_min === '' || draft.amount_min === null ? null : draft.amount_min,
                amount_max: draft.amount_max === '' || draft.amount_max === null ? null : draft.amount_max
            };

            if (categoryId) {
                payload.category_id = categoryId;
            } else {
                payload.custom_category = categoryName;
            }

            const url = rule.id ? `/api/categories/${rule.id}` : '/api/categories';
            const method = rule.id ? 'PUT' : 'POST';

            rule.saving = true;
            try {
                const response = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to save category rule.');
                }
                const updated = data.category || {};
                rule.id = updated.id;
                rule.localId = updated.id ? `rule-${updated.id}` : rule.localId;
                rule.text_to_match = updated.text_to_match || draft.text_to_match || '';
                rule.field_to_match = updated.field_to_match || draft.field_to_match || 'description';
                rule.transaction_type = updated.transaction_type || draft.transaction_type || '';
                rule.amount_min = updated.amount_min !== null && updated.amount_min !== undefined ? String(updated.amount_min) : (draft.amount_min || '');
                rule.amount_max = updated.amount_max !== null && updated.amount_max !== undefined ? String(updated.amount_max) : (draft.amount_max || '');
                const updatedCategory = updated.category || {};
                rule.category_id = updated.category_id || updatedCategory.id || draft.category_id || null;
                rule.category_name = updatedCategory.name || draft.category_name || '';
                rule.category_color = this.normalizeColor(updatedCategory.color || draft.category_color || rule.category_color);
                rule.isDirty = false;
                rule.isNew = false;
                rule.isEditing = false;
                this.categoriesError = null;
                this.resetRuleDraft(rule);
                this.updateCategoryLabels(data.labels);
                await this.fetchCustomCategories({ force: true, suppressLoader: true, refresh: true });
                await this.fetchTransactions({ reset: true, skipLoadingState: true });
            } catch (error) {
                console.error('Error saving category rule:', error);
                this.categoriesError = error.message || 'Failed to save category rule.';
            } finally {
                rule.saving = false;
            }
        },
        deleteCategoryRule: async function(rule) {
            if (!rule || rule.saving) {
                return;
            }

            if (!rule.id) {
                this.categoryRules = this.categoryRules.filter(item => item.localId !== rule.localId);
                this.updateCategoryLabels();
                this.categoriesError = null;
                return;
            }

            if (!window.confirm('Delete this category rule?')) {
                return;
            }

            rule.saving = true;
            try {
                const response = await fetch(`/api/categories/${rule.id}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to delete category rule.');
                }
                this.categoryRules = this.categoryRules.filter(item => item.localId !== rule.localId);
                this.categoriesError = null;
                this.updateCategoryLabels(data.labels);
                await this.fetchCustomCategories({ force: true, suppressLoader: true, refresh: true });
                await this.fetchTransactions({ reset: true, skipLoadingState: true });
            } catch (error) {
                console.error('Error deleting category rule:', error);
                this.categoriesError = error.message || 'Failed to delete category rule.';
            } finally {
                rule.saving = false;
            }
        },
        updateCategoryLabels: function(labels) {
            let values = Array.isArray(labels) ? labels.filter(label => !!label) : null;
            if (!values || !values.length) {
                const unique = new Set();
                this.customCategories.forEach(category => {
                    if (category.name) {
                        unique.add(category.name);
                    }
                });
                this.categoryRules.forEach(rule => {
                    if (rule.category_name) {
                        unique.add(rule.category_name);
                    }
                });
                values = Array.from(unique);
            }
            values.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
            this.categoryLabels = values;
        },
        normalizeColor: function(color) {
            const fallback = '#2C6B4F';
            if (typeof color !== 'string' || !color.trim()) {
                return fallback;
            }
            let value = color.trim();
            if (!value.startsWith('#')) {
                value = `#${value}`;
            }
            value = value.toUpperCase();
            if (!/^#([0-9A-F]{6})$/.test(value)) {
                return fallback;
            }
            return value;
        },
        toggleCategoryColorPalette: function(category) {
            if (!category) {
                return;
            }
            if (!category.isEditing) {
                return;
            }
            const targetId = category.localId;
            if (this.openCategoryColorId === targetId) {
                this.openCategoryColorId = null;
            } else {
                this.openCategoryColorId = targetId;
            }
        },
        selectCategoryColor: function(category, color) {
            const normalized = this.normalizeColor(color);
            if (category.editableColor === normalized) {
                this.openCategoryColorId = null;
                return;
            }
            category.editableColor = normalized;
            category.isDirty = true;
            this.openCategoryColorId = null;
        },
        categoryTagStyle: function(transaction) {
            if (!transaction) {
                return {};
            }
            const hex = this.normalizeColor(transaction.custom_category_color);
            const r = parseInt(hex.substr(1, 2), 16);
            const g = parseInt(hex.substr(3, 2), 16);
            const b = parseInt(hex.substr(5, 2), 16);
            const brightness = (r * 299 + g * 587 + b * 114) / 1000;
            const textColor = brightness > 150 ? '#21313c' : '#ffffff';
            return {
                backgroundColor: hex,
                color: textColor,
                borderColor: brightness > 150 ? '#d0d7de' : hex
            };
        },
        handleDocumentClick: function(event) {
            if (this.openCategoryColorId) {
                const cell = event.target.closest('.category-color-cell');
                if (!cell) {
                    this.openCategoryColorId = null;
                }
            }
            if (this.splitCategoryDropdown.rowId !== null) {
                const cell = event.target.closest('.split-category-cell');
                if (!cell) {
                    this.closeSplitCategoryDropdown();
                }
            }
            if (this.budgetCategoryDropdown.rowId !== null) {
                const cell = event.target.closest('.budget-category-cell');
                if (!cell) {
                    this.closeBudgetCategoryDropdown();
                }
            }
            if (this.transactionMenu.visible) {
                const menuRef = this.$refs.transactionContextMenu;
                const menu = Array.isArray(menuRef) ? menuRef[0] : menuRef;
                if (!menu || !menu.contains(event.target)) {
                    this.closeTransactionMenu();
                }
            }
        },
        handleGlobalKeydown: function(event) {
            if (event.key !== 'Escape') {
                return;
            }
            if (this.splitCategoryDropdown.rowId !== null) {
                this.closeSplitCategoryDropdown();
            }
            if (this.budgetCategoryDropdown.rowId !== null) {
                this.closeBudgetCategoryDropdown();
            }
            if (this.splitModal.visible) {
                if (this.splitModal.saving) {
                    return;
                }
                event.preventDefault();
                this.closeSplitModal();
                return;
            }
            if (this.openCategoryColorId) {
                this.openCategoryColorId = null;
            }
            if (this.transactionMenu.visible) {
                this.closeTransactionMenu();
            }
            if (this.mobileSidebarVisible) {
                event.preventDefault();
                this.closeMobileSidebar();
            }
        },
        fetchBanks: async function() {
            try {
                const response = await fetch('/api/banks');
                if (!response.ok) {
                    throw new Error('Failed to load banks.');
                }
                const data = await response.json();
                const previousOpen = new Set(this.openInstitutionIds);
                this.banks = (data.banks || []).map(bank => ({
                    ...bank,
                    accounts: bank.accounts || []
                }));
                this.modalBanks = this.banks;

                const retainedOpen = this.banks
                    .map(bank => bank.id)
                    .filter(id => previousOpen.has(id));

                if (retainedOpen.length) {
                    this.openInstitutionIds = retainedOpen;
                } else {
                    this.openInstitutionIds = this.banks.map(bank => bank.id);
                }

                const availableIds = new Set();
                this.banks.forEach(bank => {
                    bank.accounts.forEach(account => availableIds.add(account.id));
                });

                if (!this.selectedAccountIds.length) {
                    this.selectedAccountIds = Array.from(availableIds);
                } else {
                    const previousIds = new Set(this.selectedAccountIds);
                    const retained = this.selectedAccountIds.filter(id => availableIds.has(id));
                    // Auto-select accounts that didn't exist before (new bank added, or
                    // previously removed bank re-added with reactivated/new account IDs).
                    const newIds = Array.from(availableIds).filter(id => !previousIds.has(id));
                    this.selectedAccountIds = retained.concat(newIds);
                    if (!this.selectedAccountIds.length) {
                        this.selectedAccountIds = Array.from(availableIds);
                    }
                }
            } catch (error) {
                console.error('Error fetching banks:', error);
            }
        },
        fetchTransactions: async function(options = {}) {
            const { reset = false, skipLoadingState = false } = options;
            if (reset) {
                this.transactionsPage = 1;
            }

            const requestToken = ++this.transactionsRequestToken;

            if (!skipLoadingState) {
                this.loading = true;
            }

            if (!this.selectedAccountIds.length) {
                this.transactions = [];
                this.transactionsTotal = 0;
                this.hasMoreTransactions = false;
                if (!skipLoadingState && requestToken === this.transactionsRequestToken) {
                    this.loading = false;
                }
                return true;
            }

            try {
                const params = new URLSearchParams();
                params.append('page', this.transactionsPage);
                params.append('page_size', this.transactionsPageSize);
                params.append('sort_key', this.filters.sortKey);
                params.append('sort_desc', this.filters.sortDesc ? 'true' : 'false');

                const trimmedSearch = (this.filters.search || '').trim();
                if (trimmedSearch) {
                    params.append('search', trimmedSearch);
                }

                if (this.filters.startDate) {
                    params.append('start_date', this.filters.startDate);
                }
                if (this.filters.endDate) {
                    params.append('end_date', this.filters.endDate);
                }

                if (this.filters.amountMin !== '' && this.filters.amountMin !== null && this.filters.amountMin !== undefined) {
                    params.append('min_amount', this.filters.amountMin);
                }
                if (this.filters.amountMax !== '' && this.filters.amountMax !== null && this.filters.amountMax !== undefined) {
                    params.append('max_amount', this.filters.amountMax);
                }

                const customCategoryValue = (this.filters.customCategoryId || '').trim();
                if (customCategoryValue) {
                    params.append('custom_category_id', customCategoryValue === '__uncategorized__' ? 'none' : customCategoryValue);
                }

                if (this.selectedAccountIds.length) {
                    params.append('account_ids', this.selectedAccountIds.join(','));
                }

                const response = await fetch(`/api/transactions?${params.toString()}`);
                if (!response.ok) {
                    throw new Error('Failed to load transactions.');
                }
                const data = await response.json();
                if (requestToken !== this.transactionsRequestToken) {
                    return true;
                }
                this.transactions = data.transactions || [];
                this.transactionsTotal = data.total_count || 0;
                this.hasMoreTransactions = Boolean(data.has_more);
                if (this.transactionMenu.visible) {
                    const menuTransaction = this.transactionMenu.transaction;
                    const stillExists = menuTransaction && this.transactions.some(txn => txn.id === menuTransaction.id);
                    if (!stillExists) {
                        this.closeTransactionMenu();
                    }
                }
                if (this.editingTransactionCategoryId !== null) {
                    const stillExists = this.transactions.some(txn => txn.id === this.editingTransactionCategoryId);
                    if (!stillExists) {
                        this.cancelTransactionCategoryEdit();
                    }
                }
                return true;
            } catch (error) {
                console.error('Error fetching transactions:', error);
                return false;
            } finally {
                if (!skipLoadingState && requestToken === this.transactionsRequestToken) {
                    this.loading = false;
                }
                if (requestToken === this.transactionsRequestToken) {
                    this.updateStickyPositions();
                }
            }
        },
        toggleAllAccounts: function() {
            if (this.areAllAccountsSelected) {
                this.selectedAccountIds = [];
            } else {
                const ids = new Set();
                this.banks.forEach(bank => {
                    bank.accounts.forEach(account => ids.add(account.id));
                });
                this.selectedAccountIds = Array.from(ids);
            }
            this.$nextTick(() => {
                this.updateInstitutionCheckboxStates();
                this.handleAccountSelectionChange();
            });
        },
        toggleInstitutionSelection: function(bank) {
            const accountIds = bank.accounts.map(account => account.id);
            const selectedSet = new Set(this.selectedAccountIds);
            const allSelected = accountIds.length > 0 && accountIds.every(id => selectedSet.has(id));

            if (allSelected) {
                accountIds.forEach(id => selectedSet.delete(id));
            } else {
                accountIds.forEach(id => selectedSet.add(id));
            }

            this.selectedAccountIds = Array.from(selectedSet);
            this.$nextTick(() => {
                this.updateInstitutionCheckboxStates();
                this.handleAccountSelectionChange();
            });
        },
        handleAccountSelectionChange: function() {
            this.transactionsPage = 1;
            this.fetchTransactions({ reset: true });
        },
        isBankFullySelected: function(bank) {
            if (!bank.accounts.length) {
                return false;
            }

            const selectedSet = new Set(this.selectedAccountIds);
            return bank.accounts.every(account => selectedSet.has(account.id));
        },
        setSort: function(key) {
            if (this.filters.sortKey === key) {
                this.filters.sortDesc = !this.filters.sortDesc;
            } else {
                this.filters.sortKey = key;
                this.filters.sortDesc = key !== 'name';
            }
            this.transactionsPage = 1;
            this.fetchTransactions({ reset: true });
        },
        sortIcon: function(key) {
            if (this.filters.sortKey !== key) {
                return 'fas fa-sort text-muted';
            }
            return this.filters.sortDesc ? 'fas fa-sort-down' : 'fas fa-sort-up';
        },
        handleSearchInput: function() {
            if (this.searchDebounce) {
                window.clearTimeout(this.searchDebounce);
            }
            this.searchDebounce = window.setTimeout(() => {
                this.transactionsPage = 1;
                this.fetchTransactions({ reset: true });
            }, 300);
        },
        formatCurrency: function(amount, currency) {
            const value = Number(amount) || 0;
            const code = currency || 'USD';
            try {
                return new Intl.NumberFormat('en-US', {
                    style: 'currency',
                    currency: code,
                    minimumFractionDigits: 2
                }).format(value);
            } catch (error) {
                return `${code} ${value.toFixed(2)}`.trim();
            }
        },
        formatDashboardAmount: function(amount, currency) {
            const value = Number(amount) || 0;
            const rounded = Math.round(value);
            const code = currency || 'USD';
            try {
                return new Intl.NumberFormat('en-US', {
                    style: 'currency',
                    currency: code,
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 0
                }).format(rounded);
            } catch (error) {
                return `${code} ${rounded}`.trim();
            }
        },
        formatDate: function(isoDate) {
            if (!isoDate) {
                return '—';
            }
            const parsed = new Date(isoDate);
            if (Number.isNaN(parsed.getTime())) {
                return isoDate;
            }
            return parsed.toLocaleDateString();
        },
        applyTransactionFilters: function() {
            const start = this.filters.startDate;
            const end = this.filters.endDate;
            if (start && end && start > end) {
                this.filters.startDate = end;
                this.filters.endDate = start;
            }
            if (this.searchDebounce) {
                window.clearTimeout(this.searchDebounce);
                this.searchDebounce = null;
            }
            this.transactionsPage = 1;
            this.fetchTransactions({ reset: true });
        },
        applySpendingCategoryFilter: async function(label, month, year) {
            if (!label) {
                return;
            }

            const normalized = label.trim().toLowerCase();
            let nextCategoryId = '';
            let nextSearch = '';

            const matchedCategory = this.customCategories.find(category => {
                const name = (category.name || '').trim().toLowerCase();
                return name === normalized && category.id;
            });

            if (matchedCategory) {
                nextCategoryId = String(matchedCategory.id);
                nextSearch = '';
            } else if (normalized === 'uncategorized') {
                nextCategoryId = '__uncategorized__';
                nextSearch = '';
            } else {
                nextCategoryId = '';
                nextSearch = label;
            }

            await this.setActivePane('transactions');
            this.transactionsCollapsed = false;
            if (this.isMobileView && this.mobileSidebarVisible) {
                this.closeMobileSidebar();
            }

            this.filters.customCategoryId = nextCategoryId;
            this.filters.search = nextSearch;
            if (typeof year === 'number' && typeof month === 'number') {
                const parsedYear = Number(year);
                const parsedMonth = Number(month);
                if (!Number.isNaN(parsedYear) && !Number.isNaN(parsedMonth)) {
                    const monthIndex = parsedMonth - 1;
                    const start = new Date(parsedYear, monthIndex, 1);
                    const end = new Date(parsedYear, monthIndex + 1, 0);
                    const startMonth = String(start.getMonth() + 1).padStart(2, '0');
                    const endMonth = String(end.getMonth() + 1).padStart(2, '0');
                    const startDay = String(start.getDate()).padStart(2, '0');
                    const endDay = String(end.getDate()).padStart(2, '0');
                    this.filters.startDate = `${parsedYear}-${startMonth}-${startDay}`;
                    this.filters.endDate = `${parsedYear}-${endMonth}-${endDay}`;
                }
            }
            this.applyTransactionFilters();

            this.$nextTick(() => {
                const section = document.querySelector('.transactions-section');
                if (section) {
                    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        },
        resetFilters: function() {
            if (!this.hasActiveTransactionFilters) {
                return;
            }

            if (this.searchDebounce) {
                window.clearTimeout(this.searchDebounce);
                this.searchDebounce = null;
            }

            const defaultFilters = {
                search: '',
                sortKey: 'date',
                sortDesc: true,
                startDate: '',
                endDate: '',
                customCategoryId: '',
                amountMin: '',
                amountMax: ''
            };
            Object.assign(this.filters, defaultFilters);
            this.transactionsPage = 1;
            this.fetchTransactions({ reset: true });
        },
        syncTransactions: async function() {
            if (this.syncing) {
                return;
            }
            this.syncing = true;
            this.syncSummary = [];
            this.syncErrors = [];

            try {
                const response = await fetch('/api/transactions/sync', { method: 'POST' });
                const data = await response.json();

                if (!response.ok && response.status !== 207) {
                    const message = data.error || data.message || 'Failed to sync transactions.';
                    throw new Error(message);
                }

                this.syncSummary = data.summary || [];
                this.syncErrors = data.errors || [];
                await this.refreshData();
            } catch (error) {
                console.error('Error syncing transactions:', error);
                this.syncErrors.push({ error_message: error.message || String(error) });
            } finally {
                this.syncing = false;
            }
        },
        dismissSyncSummary: function() {
            this.syncSummary = [];
        },
        dismissSyncErrors: function() {
            this.syncErrors = [];
        },
        dismissConnectionWarning: function() {
            this.connectionWarning = null;
        },
        startReconnect: function(bankId) {
            reconnectBank(bankId);
        },
        goToNextPage: async function() {
            if (!this.hasMoreTransactions || this.loading) {
                return;
            }
            const targetPage = this.transactionsPage + 1;
            this.transactionsPage = targetPage;
            const success = await this.fetchTransactions();
            if (!success) {
                this.transactionsPage = targetPage - 1;
            }
        },
        goToPreviousPage: async function() {
            if (this.transactionsPage <= 1 || this.loading) {
                return;
            }
            const targetPage = this.transactionsPage - 1;
            this.transactionsPage = targetPage;
            const success = await this.fetchTransactions();
            if (!success) {
                this.transactionsPage = targetPage + 1;
            }
        },
        isAccordionOpen: function(bankId) {
            return this.openInstitutionIds.includes(bankId);
        },
        toggleAccordion: function(bankId) {
            if (this.isAccordionOpen(bankId)) {
                this.openInstitutionIds = this.openInstitutionIds.filter(id => id !== bankId);
            } else {
                this.openInstitutionIds = [...this.openInstitutionIds, bankId];
            }
        },
        updateInstitutionCheckboxStates: function() {
            this.banks.forEach(bank => {
                const refName = 'bankCheckbox-' + bank.id;
                const refs = this.$refs[refName];
                if (!refs) {
                    return;
                }
                const checkbox = Array.isArray(refs) ? refs[0] : refs;
                if (!checkbox) {
                    return;
                }

                const accountIds = bank.accounts.map(account => account.id);
                const selectedCount = accountIds.filter(id => this.selectedAccountIds.includes(id)).length;
                checkbox.indeterminate = selectedCount > 0 && selectedCount < accountIds.length;
            });

            const allCheckboxRefs = this.$refs.allAccountsCheckbox;
            const allCheckbox = Array.isArray(allCheckboxRefs) ? allCheckboxRefs[0] : allCheckboxRefs;
            if (allCheckbox) {
                const someSelected = this.selectedAccountIds.length > 0 && this.selectedAccountIds.length < this.totalAccountCount;
                allCheckbox.indeterminate = someSelected && !this.areAllAccountsSelected;
            }
        },
        updateStickyPositions: function() {
            const header = document.querySelector('header.sticky-top');
            const root = document.documentElement;
            if (header && root) {
                const computed = window.getComputedStyle(header);
                const marginBottom = parseFloat(computed.marginBottom || '0');
                const headerHeight = (header.offsetHeight || 0) + marginBottom;
                root.style.setProperty('--dashboard-header-height', `${headerHeight}px`);
            }
        },
        handleResize: function() {
            this.evaluateViewportState();
            this.updateStickyPositions();
        },
        removeBank: async function(bank) {
            if (!confirm(`Are you sure you want to remove your connection with ${bank.institution_name}?`)) {
                return;
            }
            try {
                const response = await fetch(`/api/remove_bank/${bank.id}`, { method: 'DELETE' });
                const data = await response.json();
                if (data.success) {
                    await this.refreshData();
                    $('#myConnectionsModal').modal('hide');
                } else {
                    alert(data.message || 'Failed to remove bank connection.');
                }
            } catch (error) {
                console.error('Error removing bank:', error);
                alert('An error occurred while removing the bank connection.');
            }
        },
        openMaintenanceModal: function() {
            // Reset state each time the modal is opened
            this.maintenance.duplicateGroups = null;
            this.maintenance.totalDuplicates = 0;
            this.maintenance.scanError = null;
            this.maintenance.deduplicationResult = null;
            $('#maintenanceModal').modal('show');
        },
        scanDuplicates: async function() {
            this.maintenance.scanning = true;
            this.maintenance.scanError = null;
            this.maintenance.duplicateGroups = null;
            this.maintenance.deduplicationResult = null;
            try {
                const resp = await fetch('/api/maintenance/duplicates');
                if (!resp.ok) {
                    throw new Error('Server returned ' + resp.status);
                }
                const data = await resp.json();
                this.maintenance.duplicateGroups = data.groups || [];
                this.maintenance.totalDuplicates = data.total_duplicates || 0;
            } catch (err) {
                this.maintenance.scanError = 'Scan failed: ' + err.message;
            } finally {
                this.maintenance.scanning = false;
            }
        },
        runDeduplication: async function() {
            if (this.maintenance.totalDuplicates === 0) return;
            if (!confirm('This will permanently mark ' + this.maintenance.totalDuplicates + ' duplicate transaction(s) as removed. Make sure you have downloaded a backup first. Continue?')) {
                return;
            }
            this.maintenance.deduplicating = true;
            this.maintenance.scanError = null;
            try {
                const resp = await fetch('/api/maintenance/deduplicate', { method: 'POST' });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.error || 'Server returned ' + resp.status);
                }
                const data = await resp.json();
                this.maintenance.deduplicationResult = data;
                this.maintenance.duplicateGroups = null;
                // Refresh categories (transaction counts changed) and transactions list
                await Promise.all([
                    this.fetchCustomCategories({ force: true }),
                    this.fetchTransactions({ reset: true }),
                ]);
            } catch (err) {
                this.maintenance.scanError = 'Deduplication failed: ' + err.message;
            } finally {
                this.maintenance.deduplicating = false;
            }
        },
        downloadBackup: function() {
            window.location.href = '/api/maintenance/backup';
        },
        fetchModalBanks: function() {
            this.modalBanks = this.banks;
        },
        openPlaidLink: function() {
            if (linkHandler) {
                linkHandler.open();
            } else {
                console.error("Plaid Link handler is not defined");
            }
        }
    },
    watch: {
        selectedSpendingYear: function() {
            this.resetOpenSpendingMonths();
        },
        isMobileView: function(newValue) {
            if (!newValue && this.mobileSidebarVisible) {
                this.mobileSidebarVisible = false;
            }
        },
        mobileSidebarVisible: function(visible) {
            if (typeof document === 'undefined') {
                return;
            }
            document.body.classList.toggle('mobile-sidebar-open', visible);
        }
    },
    mounted: async function() {
        initializePlaidLink();
        this.initializeSidebarState();
        this.evaluateViewportState();
        await this.refreshData();
        if (this.activePane === 'dashboard') {
            await this.fetchDashboard();
        } else if (this.activePane === 'budgets') {
            await this.fetchBudgets();
        }
        this.updateStickyPositions();
        window.addEventListener('resize', this.handleResize);
        document.addEventListener('click', this.handleDocumentClick, true);
        document.addEventListener('keydown', this.handleGlobalKeydown);
    },
    updated: function() {
        this.updateInstitutionCheckboxStates();
        this.updateStickyPositions();
    },
    beforeDestroy: function() {
        if (this.searchDebounce) {
            window.clearTimeout(this.searchDebounce);
        }
        window.removeEventListener('resize', this.handleResize);
        document.removeEventListener('click', this.handleDocumentClick, true);
        document.removeEventListener('keydown', this.handleGlobalKeydown);
        if (this.highlightedRuleTimeout) {
            window.clearTimeout(this.highlightedRuleTimeout);
            this.highlightedRuleTimeout = null;
        }
        if (this.highlightedCategoryTimeout) {
            window.clearTimeout(this.highlightedCategoryTimeout);
            this.highlightedCategoryTimeout = null;
        }
        if (this.splitCategoryBlurTimeout) {
            window.clearTimeout(this.splitCategoryBlurTimeout);
            this.splitCategoryBlurTimeout = null;
        }
        if (this.budgetCategoryBlurTimeout) {
            window.clearTimeout(this.budgetCategoryBlurTimeout);
            this.budgetCategoryBlurTimeout = null;
        }
        if (this.touchContextMenuTimer) {
            window.clearTimeout(this.touchContextMenuTimer);
            this.touchContextMenuTimer = null;
        }
        document.body.classList.remove('modal-open');
        document.body.classList.remove('mobile-sidebar-open');
    }
});
