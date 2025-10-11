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
        transactionsRequestToken: 0
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
        }
    },
    methods: {
        refreshData: async function() {
            this.loading = true;
            await this.fetchBanks();
            await this.fetchTransactions({ reset: true, skipLoadingState: true });
            this.loading = false;
            this.$nextTick(() => {
                this.updateInstitutionCheckboxStates();
                this.updateStickyPositions();
            });
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
    }
});
