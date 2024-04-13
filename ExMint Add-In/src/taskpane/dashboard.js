// dashboard.js

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toaster toaster-${type}`;
    if (type === 'success') {
        toast.classList.add('toaster-success'); // Add success style
    }
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => document.body.removeChild(toast), 5000);
}

Office.onReady(() => {
    // Ensures Office APIs are completely loaded before setting up interactions.
    $(document).ready(function() {
        $('.open-dashboard-btn').click(function() {
            const token = localStorage.getItem('authToken');
            if (token) {
                const dashboardUrl = window.appConfig.apiUrl + 'dashboard';
                const windowFeatures = 'toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=1200,height=800';
                window.open(dashboardUrl, '_blank', windowFeatures);
            } else {
                console.error('User not authenticated');
                showToast('Please log in to access the dashboard.', 'warning');
            }
        });
    
        $('.sync-transactions-btn').click(function() {
            syncTransactions();
        });
    
        $('#confirmLogout').click(function() {
            fetch(window.appConfig.apiUrl + 'logout', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('authToken')}`,
                    'Content-Type': 'application/json',
                    'X-Request-Source': 'Excel-Add-In'
                }
            })
            .then(response => {
                if (response.ok) {
                    localStorage.removeItem('authToken');
                    window.location.href = 'taskpane.html';
                } else {
                    throw new Error('Logout failed');
                }
            })
            .catch(error => {
                console.error('Error logging out:', error);
                showToast('Logout failed. Please try again.', 'error');
            });
        });
    });
});

function getCursors() {
    // This function needs to be async since we are interacting with Excel objects.
    return Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getItemOrNullObject('Accounts');
      await context.sync();
  
      // If the sheet does not exist, we return an empty array.
      if (sheet.isNullObject) {
        return [];
      }
  
      // Get the 'Credential ID' and 'Next Cursor' column data from the 'Accounts' table.
      const accountsTable = sheet.tables.getItem('Accounts');
      const credentialIdColumn = accountsTable.columns.getItem('Credential ID');
      const nextCursorColumn = accountsTable.columns.getItem('Next Cursor');
      const credentialIdValues = credentialIdColumn.getDataBodyRange().load('values');
      const nextCursorValues = nextCursorColumn.getDataBodyRange().load('values');
      await context.sync();
  
      // Combine 'Credential ID' and 'Next Cursor' values into 'credential_id:cursor' format.
      const credentialIdCursorPairs = credentialIdValues.values.flat().map((credentialId, index) => {
        const cursor = nextCursorValues.values.flat()[index];
        return cursor ? `${credentialId}:${cursor}` : null;
      });
  
      // Filter out any empty values and return the comma-separated list.
      return credentialIdCursorPairs.filter(pair => pair).join(',');
    }).catch(error => {
      console.error('Error getting cursors:', error);
      showToast('Failed to get cursors for transactions sync.', 'error');
      return ''; // Return an empty string in case of error.
    });
  }

  function createCard(type, bankName, operation, transactionCount, errorCode, errorMessage) {
    const card = document.createElement('div');
    card.className = `${type}-card`;
  
    const closeButton = document.createElement('button');
    closeButton.className = 'close-button';
    closeButton.innerHTML = '&times;';
    closeButton.addEventListener('click', () => {
      card.remove();
      // Hide the cards container if there are no more cards
      if (cardsContainer.children.length === 0) {
        cardsContainer.style.display = 'none';
      }
    });
  
    const content = document.createElement('div');
    if (type === 'success') {
      content.innerHTML = `
        <strong>${bankName}</strong><br>
        Successful ${operation}<br>
        ${transactionCount} Transactions retrieved
      `;
    } else if (type === 'error') {
      const errorCodeElement = document.createElement('p');
      errorCodeElement.textContent = `Error Code: ${errorCode}`;
  
      let errorMessageElement;
      if (errorCode === 'ITEM_LOGIN_REQUIRED') {
        errorMessageElement = document.createElement('p');
        errorMessageElement.textContent = 'This institution requires to renew your connection. Open the Dashboard and click the corresponding "Reconnect" button.';
      } else {
        errorMessageElement = document.createElement('p');
        errorMessageElement.textContent = `Error Message: ${errorMessage}`;
      }
  
      content.appendChild(errorCodeElement);
      content.appendChild(errorMessageElement);
    }
  
    card.appendChild(closeButton);
    card.appendChild(content);
    return card;
  }

function syncTransactions() {
    const token = localStorage.getItem('authToken');
    if (!token) {
      console.error('User not authenticated');
      showToast('Please log in to sync transactions.', 'warning');
      return;
    }
  
    const loader = document.createElement('div');
    loader.className = 'loader';
    loader.innerHTML = '<i class="fas fa-spinner fa-spin"></i><br>Loading Transactions';
    document.body.appendChild(loader);
  
    getCursors().then(cursors => {
        fetch(window.appConfig.apiUrl + 'sync', {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
            'X-Request-Source': 'Excel-Add-In',
            'x-user-token': token,
            'cursors': cursors  // Use the modified cursors format
          }
        })

      .then(response => {
        if (response.ok) {
          return response.json();
        } else {
          throw new Error('Failed to sync transactions');
        }
      })
      .then(data => {
        const errorContainer = document.getElementById('errorContainer');
        // Clear any existing error cards
        cardsContainer.innerHTML = '';
        const banksWithErrors = new Set();
        
        // Process each bank item
        data.banks.forEach(bank => {
            // Check if the bank item contains an 'error' key
            if (bank.error) {
            const errorCode = bank.error.error_code;
            const errorMessage = bank.error.error_message;

            // Create an error card for the bank
            const errorCard = createCard('error', bank.institution_name, null, null, errorCode, errorMessage);

            // Append the error card to the cards container
            cardsContainer.appendChild(errorCard);
            // Add the bank to the set of banks with errors
            banksWithErrors.add(bank.institution_name);
            } else {
            // Calculate the total transaction count for the bank
            const transactionCount = bank.accounts.reduce((total, account) => total + account.transactions.length, 0);

            // Create a success card for the bank
            const successCard = createCard('success', bank.institution_name, bank.operation, transactionCount);

            // Append the success card to the cards container
            cardsContainer.appendChild(successCard);
            }
        });

        // Hide the cards container if there are no cards
        if (cardsContainer.children.length === 0) {
            cardsContainer.style.display = 'none';
        } else {
            cardsContainer.style.display = 'block';
        }

        Excel.run(function (context) {
            const workbook = context.workbook;
            let accountsSheet = workbook.worksheets.getItemOrNullObject('Accounts');
            let transactionsSheet = workbook.worksheets.getItemOrNullObject('Transactions');
    
            return context.sync()
                .then(() => {
                    // If the Accounts sheet doesn't exist, create it.
                    if (accountsSheet.isNullObject) {
                        accountsSheet = workbook.worksheets.add('Accounts');
                        let accountsHeader = [["Institution Name", "Credential ID", "Next Cursor", "Balance", "Mask", "Name", "Plaid Account ID", "Subtype", "Type"]];
                        let accountsTable = accountsSheet.tables.add('A1:I1', true);
                        accountsTable.name = 'Accounts';
                        accountsTable.getHeaderRowRange().values = accountsHeader;
                    }
    
                    // If the Transactions sheet doesn't exist, create it.
                    if (transactionsSheet.isNullObject) {
                        transactionsSheet = workbook.worksheets.add('Transactions');
                        let transactionsHeader = [["Account ID", "Action", "Amount", "Categories", "Date", "ISO Currency Code", "Merchant Name", "Name", "Payment Channel", "Pending", "Transaction ID"]];
                        let transactionsTable = transactionsSheet.tables.add('A1:K1', true);
                        transactionsTable.name = 'Transactions';
                        transactionsTable.getHeaderRowRange().values = transactionsHeader;
                    }
    
                    return context.sync();
                })
                .then(() => {
                    let accountsData = [];
                    let transactionsData = [];
                    try{
                        if (data.banks) {
                            // Loop through each bank
                            data.banks.forEach(bank => {
                                // Skip the bank if it has errors
                                if (banksWithErrors.has(bank.institution_name)) {
                                    return;
                                }
                                // Loop through each account within the bank
                                bank.accounts.forEach(account => {
                                    let accountRow = [
                                        bank.institution_name,
                                        bank.credential_id,  // Add the Credential ID field
                                        bank.next_cursor,
                                        account.balance,
                                        account.mask,
                                        account.name,
                                        account.plaid_account_id,
                                        account.subtype,
                                        account.type
                                    ];
                                    accountsData.push(accountRow);
            
                                    // Loop through each transaction within the account
                                    account.transactions.forEach(transaction => {
                                        let categories = transaction.category ? transaction.category.join(', ') : '';
                                        let transactionRow = [
                                            account.plaid_account_id,
                                            transaction.action,
                                            transaction.amount,
                                            categories,
                                            // Convert date to local time format
                                            new Date(transaction.date).toLocaleString(),
                                            transaction.iso_currency_code,
                                            transaction.merchant_name || '',  // Use empty string if null
                                            transaction.name,
                                            transaction.payment_channel,
                                            transaction.pending,
                                            transaction.transaction_id
                                        ];
                                        transactionsData.push(transactionRow);
                                    });
                                });
                            });
                        }
                    } catch (error){
                        showToast('Failed to sync transactions of one bank.', 'error');
                    }
                    // Add data to the Accounts table
                    let accountsTable = workbook.tables.getItem('Accounts');
                    accountsTable.rows.add(null, accountsData);
    
                    // Add data to the Transactions table
                    let transactionsTable = workbook.tables.getItem('Transactions');
                    transactionsTable.rows.add(null, transactionsData);
    
                    return context.sync();
                });
        }).then(function () {
            showToast('Transactions synced successfully.', 'success');
        }).catch(function (error) {
            console.error('Error syncing transactions:', error);
            showToast('Failed to sync transactions. Please try again.', 'error');
        }).finally(function () {
            document.body.removeChild(loader);
        });
    })
    .catch(error => {
        console.error('Error syncing transactions:', error);
        showToast('Failed to sync transactions. Please try again.', 'error');
        document.body.removeChild(loader);
      });
  })
  .catch(error => {
    console.error('Error getting cursors:', error);
    showToast('Failed to get cursors for transactions sync.', 'error');
    document.body.removeChild(loader);
  });
}