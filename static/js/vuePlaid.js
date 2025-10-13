//vuePlaid.js
const linkButton = document.getElementById('link-button');
let linkHandler = null;

// Function to handle the creation of the link token, adapted to support update mode
async function createLinkToken(access_token = null) {
    const payload = {};
    if (access_token) {
        payload.access_token = access_token;
    }
    const response = await fetch('/create_link_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (!response.ok) {
        // Handle HTTP errors (e.g., network issues, endpoint not found, server errors)
        console.error("Failed to create link token:", response.statusText);
        throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log("Received link token:", data); // Debugging
    return data.link_token; // Ensure to handle the case where this might be undefined due to errors
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

// Function to initiate the reconnect process for a bank
async function reconnectBank(bankId) {
    //console.log("Initiating reconnect for Bank ID:", bankId);

    try {
        const response = await fetch(`/api/get_access_token/${bankId}`, { method: 'GET' });
        if (!response.ok) throw new Error('Failed to fetch access token.');

        const {access_token} = await response.json();
        //console.log("Fetched access token for update:", access_token);

        const linkToken = await createLinkToken(access_token); 
        //console.log("Received link token for update mode:", linkToken);

        linkHandler = Plaid.create({
            token: linkToken,
            onSuccess: async (publicToken, metadata) => {
                console.log("OnSuccess block started")
                let refreshResponse = await fetch('/handle_token_and_accounts', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        public_token: publicToken,
                        institution_name: metadata.institution.name,
                        is_refresh: true, // Indicate this is a refresh operation
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

        //console.log("Opening Plaid Link...");

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

// Event Listener for Plaid Link button
document.addEventListener('DOMContentLoaded', () => {
    linkButton.addEventListener('click', () => {
        if (linkHandler) {
            linkHandler.open();
        } else {
            console.error("Plaid Link handler is not defined");
        }
    });

    // Initialize Plaid Link
    initializePlaidLink();
});

const app = new Vue({
    el: '#vue-app',
    delimiters: ['[[', ']]'],
    data: {
        banks: [],
        selectedAccountIds: [],
        transactions: [],
        categoryRules: [],
        categoryLabels: [],
        categoriesError: null,
        filters: {
            search: '',
            sortKey: 'date',
            sortDesc: true
        },
        syncing: false,
        loading: true,
        syncSummary: [],
        syncErrors: [],
        modalBanks: [],
        openInstitutionIds: [],
        transactionsPage: 1,
        transactionsPageSize: 200,
        transactionsTotal: 0,
        hasMoreTransactions: false,
        searchDebounce: null,
        transactionsRequestToken: 0,
        activePane: 'transactions',
        transactionsCollapsed: false,
        categoriesLoading: false,
        categoriesLoaded: false,
        nextCategoryTempId: 0,
        openColorRuleId: null,
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
        transactionMenu: {
            visible: false,
            x: 0,
            y: 0,
            transaction: null
        },
        highlightedRuleLocalId: null,
        highlightedRuleTimeout: null,
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
        nextSplitRowId: 0
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
            const values = new Set();
            this.categoryRules.forEach(rule => {
                if (rule.label) {
                    values.add(rule.label);
                }
            });
            this.transactions.forEach(txn => {
                if (txn.custom_category) {
                    values.add(txn.custom_category);
                }
                if (Array.isArray(txn.category)) {
                    txn.category.forEach(cat => {
                        if (cat) {
                            values.add(cat);
                        }
                    });
                }
            });
            return Array.from(values).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
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
        splitCategoryOptions: function() {
            return this.transactionCategoryOptions;
        }
    },
    methods: {
        refreshData: async function() {
            this.loading = true;
            try {
                await this.fetchBanks();
                await this.fetchTransactions({ reset: true, skipLoadingState: true });
                if (this.activePane === 'categories') {
                    await this.fetchCategories({ refresh: true, suppressLoader: true });
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
            if (pane !== 'transactions') {
                this.cancelTransactionCategoryEdit();
            }
            if (pane === 'categories') {
                if (!this.categoriesLoaded || (!this.categoryRules.length && !this.categoriesLoading)) {
                    await this.fetchCategories();
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
        toggleTransactionsCollapse: function() {
            this.transactionsCollapsed = !this.transactionsCollapsed;
            this.$nextTick(() => {
                this.updateStickyPositions();
            });
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

            const payload = { label: trimmed };
            if (trimmed) {
                const matchingRule = this.categoryRules.find(rule => rule.label === trimmed);
                if (matchingRule && matchingRule.color) {
                    payload.color = matchingRule.color;
                }
            }

            transaction.savingCategory = true;
            try {
                const response = await fetch(`/api/transactions/${transaction.id}/category`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to update category.');
                }
                if (data.transaction) {
                    Object.assign(transaction, data.transaction);
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
            const description = transaction.name || '';
            const newRule = this.addCategoryRule({
                text_to_match: description,
                field_to_match: 'description',
                transaction_type: '',
                label: ''
            });
            this.highlightRuleRow(newRule.localId, { focusField: 'label' });
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
            if (!contextTransaction || contextTransaction.is_split_child) {
                return;
            }
            const transaction = this.transactions.find(txn => txn.id === contextTransaction.id) || contextTransaction;
            this.openSplitModal(transaction);
        },
        openSplitModal: async function(transaction) {
            if (!transaction) {
                return;
            }
            let parentSnapshot = transaction;
            let fetchedChildren = [];
            if (transaction.has_split_children) {
                try {
                    const response = await fetch(`/api/transactions/${transaction.id}/split`);
                    if (response.ok) {
                        const data = await response.json();
                        const childPayload = Array.isArray(data.children) ? data.children : [];
                        fetchedChildren = childPayload;
                        if (data.parent) {
                            parentSnapshot = data.parent;
                        }
                    }
                } catch (error) {
                    console.error('Error fetching split details:', error);
                }
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
                    const key = category.toLowerCase();
                    if (categorySet.has(key)) {
                        errors.push('Split categories must be unique.');
                    } else {
                        categorySet.add(key);
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
            } else if (!this.categoriesLoaded && !this.categoriesLoading) {
                await this.fetchCategories();
            }
        },
        focusRuleById: async function(ruleId) {
            if (!ruleId) {
                return;
            }
            await this.ensureCategoriesPane();
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
        focusRuleInput: function(localId, target) {
            if (!localId || !target) {
                return;
            }
            const refName = target === 'label' ? `ruleLabelInput-${localId}` : `ruleTextInput-${localId}`;
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
            const text = (rule.text_to_match || '').trim();
            const label = (rule.label || '').trim();
            if (text && label) {
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
        fetchCategories: async function(options = {}) {
            const { force = false, suppressLoader = false } = options;
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
                    throw new Error('Failed to load categories.');
                }
                const data = await response.json();
                this.categoryRules = (data.categories || []).map(rule => this.prepareCategoryRule(rule));
                this.categoriesLoaded = true;
                this.updateCategoryLabels(data.labels);
            } catch (error) {
                console.error('Error fetching categories:', error);
                this.categoriesError = error.message || 'Failed to load categories.';
            } finally {
                this.categoriesLoading = false;
            }
        },
        prepareCategoryRule: function(raw) {
            const ruleId = raw.id || null;
            const normalizedColor = this.normalizeColor(raw.color);
            return {
                id: ruleId,
                localId: ruleId ? `rule-${ruleId}` : `local-${Date.now()}-${++this.nextCategoryTempId}`,
                text_to_match: raw.text_to_match || '',
                field_to_match: raw.field_to_match || 'description',
                transaction_type: raw.transaction_type || '',
                amount_min: raw.amount_min !== null && raw.amount_min !== undefined ? String(raw.amount_min) : '',
                amount_max: raw.amount_max !== null && raw.amount_max !== undefined ? String(raw.amount_max) : '',
                color: normalizedColor,
                label: raw.label || '',
                isDirty: false,
                isNew: false,
                saving: false
            };
        },
        addCategoryRule: function(initial = {}) {
            const tempId = `new-${Date.now()}-${++this.nextCategoryTempId}`;
            const defaultColor = initial.color ? this.normalizeColor(initial.color) : this.categoryPalette[0];
            const newRule = {
                id: null,
                localId: tempId,
                text_to_match: initial.text_to_match || '',
                field_to_match: initial.field_to_match || 'description',
                transaction_type: initial.transaction_type || '',
                amount_min: initial.amount_min || '',
                amount_max: initial.amount_max || '',
                color: defaultColor,
                label: initial.label || '',
                isDirty: initial.isDirty !== undefined ? initial.isDirty : true,
                isNew: true,
                saving: false
            };
            this.categoryRules.unshift(newRule);
            this.categoriesLoaded = true;
            this.categoriesError = null;
            this.updateCategoryLabels();
            return newRule;
        },
        markRuleDirty: function(rule) {
            if (!rule) {
                return;
            }
            rule.isDirty = true;
            this.categoriesError = null;
        },
        saveCategoryRule: async function(rule) {
            if (!rule || rule.saving) {
                return;
            }
            const text = (rule.text_to_match || '').trim();
            const label = (rule.label || '').trim();
            if (!text || !label) {
                this.categoriesError = 'Both "Text to match" and "Custom Category" are required.';
                return;
            }

            const payload = {
                text_to_match: text,
                field_to_match: rule.field_to_match || 'description',
                transaction_type: rule.transaction_type || null,
                amount_min: rule.amount_min === '' || rule.amount_min === null ? null : rule.amount_min,
                amount_max: rule.amount_max === '' || rule.amount_max === null ? null : rule.amount_max,
                label: label,
                color: this.normalizeColor(rule.color)
            };

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
                rule.text_to_match = updated.text_to_match || '';
                rule.field_to_match = updated.field_to_match || 'description';
                rule.transaction_type = updated.transaction_type || '';
                rule.amount_min = updated.amount_min !== null && updated.amount_min !== undefined ? String(updated.amount_min) : '';
                rule.amount_max = updated.amount_max !== null && updated.amount_max !== undefined ? String(updated.amount_max) : '';
                rule.color = this.normalizeColor(updated.color);
                rule.label = updated.label || '';
                rule.isDirty = false;
                rule.isNew = false;
                this.categoriesError = null;
                this.updateCategoryLabels(data.labels);
                this.openColorRuleId = null;
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
                await this.fetchTransactions({ reset: true, skipLoadingState: true });
            } catch (error) {
                console.error('Error deleting category rule:', error);
                this.categoriesError = error.message || 'Failed to delete category rule.';
            } finally {
                rule.saving = false;
            }
        },
        updateCategoryLabels: function(labels) {
            let values = Array.isArray(labels) ? labels.slice() : null;
            if (!values || !values.length) {
                const unique = new Set();
                this.categoryRules.forEach(rule => {
                    if (rule.label) {
                        unique.add(rule.label);
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
        toggleRulePalette: function(rule) {
            if (!rule) {
                return;
            }
            const targetId = rule.localId;
            if (this.openColorRuleId === targetId) {
                this.openColorRuleId = null;
            } else {
                this.openColorRuleId = targetId;
            }
        },
        selectRuleColor: function(rule, color) {
            const normalized = this.normalizeColor(color);
            if (rule.color === normalized) {
                this.openColorRuleId = null;
                return;
            }
            rule.color = normalized;
            this.markRuleDirty(rule);
            this.openColorRuleId = null;
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
            if (this.openColorRuleId) {
                const cell = event.target.closest('.category-color-cell');
                if (!cell) {
                    this.openColorRuleId = null;
                }
            }
            if (this.splitCategoryDropdown.rowId !== null) {
                const cell = event.target.closest('.split-category-cell');
                if (!cell) {
                    this.closeSplitCategoryDropdown();
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
            if (this.splitModal.visible) {
                if (this.splitModal.saving) {
                    return;
                }
                event.preventDefault();
                this.closeSplitModal();
                return;
            }
            if (this.openColorRuleId) {
                this.openColorRuleId = null;
            }
            if (this.transactionMenu.visible) {
                this.closeTransactionMenu();
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
                    this.selectedAccountIds = this.selectedAccountIds.filter(id => availableIds.has(id));
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
        resetFilters: function() {
            if (!this.filters.search && this.filters.sortKey === 'date' && this.filters.sortDesc) {
                return;
            }

            if (this.searchDebounce) {
                window.clearTimeout(this.searchDebounce);
                this.searchDebounce = null;
            }

            this.filters.search = '';
            this.filters.sortKey = 'date';
            this.filters.sortDesc = true;
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
        fetchModalBanks: function() {
            this.modalBanks = this.banks;
        }
    },
    mounted: async function() {
        await this.refreshData();
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
        document.body.classList.remove('modal-open');
    }
});
