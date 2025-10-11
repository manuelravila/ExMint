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
        allTransactions: [],
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
        loadingMore: false
    },
    computed: {
        totalAccountCount: function() {
            return this.banks.reduce((count, bank) => count + bank.accounts.length, 0);
        },
        areAllAccountsSelected: function() {
            return this.totalAccountCount > 0 && this.selectedAccountIds.length === this.totalAccountCount;
        },
        loadedTransactionsCount: function() {
            return this.allTransactions.length;
        },
        displayedTransactions: function() {
            if (!this.selectedAccountIds.length) {
                return [];
            }

            const activeIds = new Set(this.selectedAccountIds);
            let filtered = this.allTransactions.filter(txn => activeIds.has(txn.account_id));

            if (this.filters.search) {
                const term = this.filters.search.trim().toLowerCase();
                filtered = filtered.filter(txn => {
                    const components = [
                        txn.name,
                        txn.merchant_name,
                        (txn.category || []).join(' '),
                        txn.account_name,
                        txn.institution_name
                    ].join(' ');
                    return components.toLowerCase().includes(term);
                });
            }

            const sortKey = this.filters.sortKey;
            const sorted = filtered.slice().sort((a, b) => {
                const key = sortKey;
                let result = 0;

                if (key === 'date') {
                    const aTime = a.date ? new Date(a.date).getTime() : 0;
                    const bTime = b.date ? new Date(b.date).getTime() : 0;
                    result = aTime - bTime;
                } else if (key === 'amount') {
                    const aAmount = Number(a.amount) || 0;
                    const bAmount = Number(b.amount) || 0;
                    result = aAmount - bAmount;
                } else {
                    const aValue = (a[key] || '').toString().toLowerCase();
                    const bValue = (b[key] || '').toString().toLowerCase();
                    result = aValue.localeCompare(bValue);
                }

                if (result === 0 && key !== 'date') {
                    const aTime = a.date ? new Date(a.date).getTime() : 0;
                    const bTime = b.date ? new Date(b.date).getTime() : 0;
                    result = aTime - bTime;
                }

                return this.filters.sortDesc ? result * -1 : result;
            });

            return sorted;
        }
    },
    methods: {
        refreshData: async function() {
            this.loading = true;
            await this.fetchBanks();
            await this.fetchTransactions({ reset: true });
            this.loading = false;
            this.$nextTick(this.updateInstitutionCheckboxStates);
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
            const { reset = false } = options;
            try {
                if (reset) {
                    this.transactionsPage = 1;
                    this.hasMoreTransactions = false;
                    this.loadingMore = false;
                    this.allTransactions = [];
                }

                const params = new URLSearchParams();
                params.append('page', this.transactionsPage);
                params.append('page_size', this.transactionsPageSize);

                const response = await fetch(`/api/transactions?${params.toString()}`);
                if (!response.ok) {
                    throw new Error('Failed to load transactions.');
                }
                const data = await response.json();
                const transactions = data.transactions || [];

                if (reset) {
                    this.allTransactions = transactions;
                } else {
                    const existingIds = new Set(this.allTransactions.map(txn => txn.id));
                    const merged = [...this.allTransactions];
                    transactions.forEach(txn => {
                        if (!existingIds.has(txn.id)) {
                            merged.push(txn);
                        }
                    });
                    this.allTransactions = merged;
                }

                this.transactionsTotal = data.total_count || this.allTransactions.length;
                this.hasMoreTransactions = Boolean(data.has_more);
                return true;
            } catch (error) {
                console.error('Error fetching transactions:', error);
                return false;
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
            this.$nextTick(this.updateInstitutionCheckboxStates);
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
            this.$nextTick(this.updateInstitutionCheckboxStates);
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
                this.filters.sortDesc = key !== 'name'; // Default to ascending for name
            }
        },
        sortIcon: function(key) {
            if (this.filters.sortKey !== key) {
                return 'fas fa-sort text-muted';
            }
            return this.filters.sortDesc ? 'fas fa-sort-down' : 'fas fa-sort-up';
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
            this.filters.search = '';
            this.filters.sortKey = 'date';
            this.filters.sortDesc = true;
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
        loadMoreTransactions: async function() {
            if (!this.hasMoreTransactions || this.loadingMore) {
                return;
            }

            this.loadingMore = true;
            const nextPage = this.transactionsPage + 1;
            try {
                this.transactionsPage = nextPage;
                const success = await this.fetchTransactions({ reset: false });
                if (!success) {
                    this.transactionsPage = nextPage - 1;
                }
            } finally {
                this.loadingMore = false;
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
    },
    updated: function() {
        this.updateInstitutionCheckboxStates();
    }
});
