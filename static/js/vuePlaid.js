//plaid_integration.js
const linkButton = document.getElementById('link-button');
let linkHandler = null;

// Function to handle the creation of the link token, adapted to support update mode
async function createLinkToken(access_token = null) {
    // Always prepare a JSON payload, with access_token included only if provided
    let body = JSON.stringify({ user_id: "your_user_id", access_token: access_token }); // Ensure you have a user_id or similar if needed

    const response = await fetch('/create_link_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body // This now consistently sends a JSON object, with or without access_token
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
    console.log("Calling initializeLink");
    const linkToken = await createLinkToken();
    console.log("Received link token:", linkToken);
    //console.log(linkToken);  // Add this line for debugging
    linkHandler = Plaid.create({
        token: linkToken,
        onSuccess: async (publicToken, metadata) => {
            // Send the public token to the server
            const institutionName = metadata.institution.name;  // Get institution name from metadata
            const response = await fetch('/get_access_token', {
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
            //console.log("Access Token:", accessToken);  // Debugging: log the access token
            fetchAndDisplayTransactions(accessToken); // Call the function to fetch and display transactions
            if (response.ok && data.status === 'success') {
                console.log("Access Token Added Successfully");
                if (typeof app !== 'undefined' && app.fetchBanks) {
                    app.fetchBanks(); // Refresh the banks data in Vue.js
                } else {
                    console.error("Vue instance 'app' is not defined.");
                }
                setTimeout(() => {
                    window.location.href = '/dashboard';
                }, 500);
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
    console.log("Initiating reconnect for Bank ID:", bankId);

    try {
        // Fetch the access_token for the bank that requires reconnection
        const response = await fetch(`/api/get_access_token/${bankId}`, { method: 'GET' });
        if (!response.ok) throw new Error('Failed to fetch access token.');

        const data = await response.json();
        const access_token = data.access_token;
        console.log("Fetched access token for update:", access_token);

        // Correctly pass access_token to generate link token for update mode
        const linkToken = await createLinkToken(access_token); // Ensure createLinkToken is adjusted to accept access_token properly
        console.log("Received link token for update mode:", linkToken);

        // Use the link token to initialize Plaid Link in update mode
        // Adjust your existing Plaid Link initialization logic as needed
        linkHandler = Plaid.create({
            token: linkToken,
            onSuccess: async (publicToken, metadata) => {
                // Exchange public token for access token and refresh accounts
                let response = await fetch('/refresh_accounts', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        credential_id: bankId, // Assuming you have a way to map bankId to credential_id
                        access_token: accessToken // You'll need to securely handle access_token
                    })
                });
                if (response.ok) {
                    console.log("Accounts refreshed successfully");
                    // Refresh dashboard
                    window.location.href = '/dashboard.html';
                } else {
                    console.error("Failed to refresh accounts");
                }
            },
            
            onExit: (err, metadata) => {
                // Handle exit scenario, e.g., user closed the modal without completing the process
                console.log("User exited link modal", err, metadata);
            },
            // Include other necessary configuration options as per your application's needs
        });

        // Now open the Plaid Link modal for the user to reconnect their bank
        linkHandler.open();
    } catch (error) {
        console.error("Error during bank reconnect:", error);
    }
}



// Function to fetch and display transactions
async function fetchAndDisplayTransactions(accessToken) {
    
    // Prepare the payload
    const payload = JSON.stringify({ access_token: accessToken });

    // Use the access token to fetch transactions
    console.log("Sending payload:", payload); // Debug: Log the access token being sent

    const response = await fetch('/transactions', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: payload,  // send the access token
    });

    if (response.status === 202) {
    // Handle the case where the product is not ready
    alert('Transaction data is not ready yet. Please try again later.');
    return;
    }

    const transactions = await response.json();

    if (!Array.isArray(transactions)) {
        console.error('Transactions is not an array:', transactions);
        return;
    }

    // Display transactions in the 'transactions' div
    const transactionsDiv = document.getElementById('transactions');
    transactionsDiv.innerHTML = '<h2>Transactions</h2>';
    transactions.forEach(transaction => {
        transactionsDiv.innerHTML += `<p>${transaction.name}: $${transaction.amount}</p>`;
    });
}

// Initialize Plaid Link after Vue instance
async function initializePlaidLink() {
    try {
        await initializeLink();
        console.log("Plaid Link initialized", linkHandler);
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

new Vue({
    el: '#vue-app',
    delimiters: ['[[', ']]'],  
    data: {
        banks: [],
        accounts: [],
        selectedBankId: null,
        modalBanks: [] 
    },
    methods: {
        fetchBanks: function() {
            fetch('/api/banks')
                .then(response => response.json())
                .then(data => {
                    this.banks = data.banks.map(bank => ({
                        ...bank,
                        requires_update: bank.requires_update  // Assuming your backend API provides this information
                    }));
                    this.fetchAccounts();
                });
        },
        fetchAccounts: function(bankId = null) {
            let url = '/api/accounts';
            if (bankId) {
                url += `?bank_id=${bankId}`;
                this.selectedBankId = bankId;
            } else {
                this.selectedBankId = null;
            }
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    this.accounts = data.accounts;
                });
        },
        toggleBankSelection: function(bankId) {
            if (this.selectedBankId === bankId) {
                this.selectedBankId = null;
                this.fetchAccounts(); // Fetch all accounts if the same bank is clicked again
            } else {
                this.selectedBankId = bankId;
                this.fetchAccounts(bankId);
            }
        },
        removeBank: function(bank) {
            console.log("Attempting to remove bank:", bank);
        
            if (confirm(`Are you sure you want to remove your connection with ${bank.institution_name}?`)) {
                console.log("Confirmed removal of bank:", bank);
        
                fetch('/api/remove_bank/' + bank.id, { method: 'DELETE' })
                    .then(response => response.json())
                    .then(data => {
                        console.log("Response data:", data);
                        if (data.success) {
                            console.log("Bank connection removed:", bank);
                            window.location.href = '/dashboard?connections_modal_open=true';
                        } else {
                            console.log("Error removing bank:", data.message);
                            alert(data.message);
                        }
                    })
                    .catch(error => {
                        console.error('Error:', error);
                    });
            } else {
                console.log("Bank removal cancelled for:", bank);
            }
        },
        
        toggleAccountEnable: function(accountId, isEnabled) {
            const url = `/api/accounts/${isEnabled ? 'enable' : 'disable'}/${accountId}`;
            fetch(url, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        console.log(`Account ${isEnabled ? 'enabled' : 'disabled'}:`, accountId);
                    } else {
                        console.error('Error toggling account:', data.message);
                        alert(`Failed to ${isEnabled ? 'enable' : 'disable'} account. Please try again.`);
                        // Rollback the switch state on failure
                        this.fetchAccounts();
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    this.fetchAccounts(); // Ensure UI consistency by reloading accounts
                });
        },  
        
    },
    mounted: function() {
        this.fetchBanks();
        console.log("Vue instance mounted");
    }
});