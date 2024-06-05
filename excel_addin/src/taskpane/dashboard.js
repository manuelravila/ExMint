// dashboard.js

console.log("Dashboard script loaded");

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

$('.sync-transactions-btn').click(function() {
  syncTransactions();
});

Office.onReady(() => {
  // Ensures Office APIs are completely loaded before setting up interactions.
  $(document).ready(function() {
      $('.open-dashboard-btn').click(function() {
          const token = localStorage.getItem('authToken');
          if (token) {
              const dashboardUrl = window.appConfig.apiUrl + '/dashboard';
              const windowFeatures = 'toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=1200,height=800';
              window.open(dashboardUrl, '_blank', windowFeatures);
          } else {
              console.error('User not authenticated');
              showToast('Please log in to access the dashboard.', 'warning');
          }
      });
  
      $('#confirmLogout').click(function() {
          fetch(window.appConfig.apiUrl + '/logout', {
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
  card.className = `${type}-card ${bankName.replace(/\s+/g, '-')}-card`;

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

let isSyncing = false;

function syncTransactions() {
  if (isSyncing) {
      console.log('Sync is already in progress');
      return;
  }

  isSyncing = true;
  console.log('Syncing started');

  const token = localStorage.getItem('authToken');
  if (!token) {
      console.error('User not authenticated');
      showToast('Please log in to sync transactions.', 'warning');
      isSyncing = false;
      console.log('Syncing aborted: user not authenticated');
      return;
  }

  const loader = document.createElement('div');
  loader.className = 'loader';
  loader.innerHTML = '<i class="fas fa-spinner fa-spin"></i><br>Loading Transactions';
  document.body.appendChild(loader);

  Excel.run(context => {
      const workbook = context.workbook;
      return workbook.load('worksheets').context.sync()
          .then(() => importTemplateSheets(context, workbook))
          .then(() => getCursors())
          .then(cursors => {
              console.log('Cursors retrieved:', cursors);
              return fetch(window.appConfig.apiUrl + '/sync', {
                  method: 'GET',
                  headers: {
                      'Authorization': `Bearer ${token}`,
                      'Content-Type': 'application/json',
                      'X-Request-Source': 'Excel-Add-In',
                      'x-user-token': token,
                      'cursors': cursors
                  }
              });
          })
          .then(response => {
              if (response.ok) {
                  console.log('Sync response OK');
                  return response.json();
              } else {
                  console.log('Sync response failed');
                  throw new Error('Failed to sync transactions');
              }
          })
          .then(data => {
              console.log('Transaction data retrieved:', data);
              return processTransactionData(context, workbook, data);
          })
          .catch(error => {
              console.error('Error syncing transactions:', error);
              showToast('Failed to sync transactions. Please try again.', 'error');
          })
          .finally(() => {
              isSyncing = false;
              const loader = document.querySelector('.loader');
              if (loader) {
                  document.body.removeChild(loader);
              }
              console.log('Syncing process completed, cleaning up.');
          });
  }).catch(error => {
      console.error('Error in Excel.run:', error);
      showToast('An error occurred. Please try again.', 'error');
  });
}

function processTransactionData(context, workbook, data) {
  const banksWithErrors = new Set();

  // Clear existing cards before adding new ones
  const cardsContainer = document.getElementById('cardsContainer');
  while (cardsContainer.firstChild) {
      cardsContainer.removeChild(cardsContainer.firstChild);
  }

  // Process each bank item
  if (data.banks) {
      data.banks.forEach(bank => {
          if (bank.error) {
              const errorCode = bank.error.error_code;
              const errorMessage = bank.error.error_message;
              createErrorCard(bank.institution_name, errorCode, errorMessage);
              banksWithErrors.add(bank.institution_name);
          } else {
              const transactionCount = bank.accounts.reduce((total, account) => total + (account.transactions ? account.transactions.length : 0), 0);
              createSuccessCard(bank.institution_name, bank.operation, transactionCount);
          }
      });
  }

  return insertTransactionData(context, workbook, data, banksWithErrors)
      .then(() => context.sync())
      .then(() => {
          showToast('Transactions synced successfully.', 'success');
          console.log('Transaction data processed and synced successfully.');
      })
      .catch(error => {
          console.error('Error syncing transactions:', error);
          showToast('Failed to sync transactions. Please try again.', 'error');
      });
}

function importTemplateSheets(context, workbook) {
  return new Promise((resolve, reject) => {
      // Check if the template sheets already exist
      const sheets = workbook.worksheets;
      const sheetNames = ['Dashboard', 'Accounts', 'Transactions', 'Conf'];
      let existingSheets = [];
      
      sheets.load('items/name');
      
      context.sync().then(() => {
          sheets.items.forEach(sheet => {
              if (sheetNames.includes(sheet.name)) {
                  existingSheets.push(sheet.name);
              }
          });
          
          // Only import template sheets if they do not already exist
          if (existingSheets.length === 0) {
              fetch('/assets/template.xlsx')
                  .then(response => response.arrayBuffer())
                  .then(arrayBuffer => {
                      const base64String = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));
                      const options = { sheetNamesToInsert: [] };
                      workbook.insertWorksheetsFromBase64(base64String, options);
                      return context.sync().then(resolve).catch(reject);
                  })
                  .catch(reject);
          } else {
              resolve();
          }
      }).catch(reject);
  });
}

function insertTransactionData(context, workbook, data, banksWithErrors) {
  const accountsData = [];
  const transactionsData = [];

  if (data.banks) {
      data.banks.forEach(bank => {
          if (banksWithErrors.has(bank.institution_name)) {
              return;
          }

          bank.accounts.forEach(account => {
              const accountRow = [
                  bank.institution_name,
                  bank.credential_id,
                  bank.next_cursor,
                  account.balance,
                  account.mask,
                  account.name,
                  account.plaid_account_id,
                  account.subtype,
                  account.type
              ];
              accountsData.push(accountRow);

              if (account.transactions) {
                  account.transactions.forEach(transaction => {
                      const categories = transaction.category ? transaction.category.join(', ') : '';
                      // Convert the date string to an Excel datetime value
                      const jsDate = new Date(transaction.date);
                      const excelDate = jsDate.getTime() / (1000 * 60 * 60 * 24) + 25569 + (jsDate.getTimezoneOffset() / (60 * 24));

                      const transactionRow = [
                          account.plaid_account_id,
                          transaction.action,
                          -1 * transaction.amount,
                          categories,
                          excelDate, // Use the converted Excel datetime value here
                          transaction.iso_currency_code,
                          transaction.merchant_name || '',
                          transaction.name,
                          transaction.payment_channel,
                          transaction.pending,
                          transaction.transaction_id
                      ];
                      transactionsData.push(transactionRow);
                  });
              }
          });
      });
  }

  const accountsTable = workbook.tables.getItem('Accounts');
  const transactionsTable = workbook.tables.getItem('Transactions');

  // Clear existing data in the tables
  accountsTable.clearFilters();
  accountsTable.getDataBodyRange().clear();
  transactionsTable.clearFilters();
  transactionsTable.getDataBodyRange().clear();

  // Load table columns
  const transactionsHeaderRange = transactionsTable.getHeaderRowRange().load('values');
  
  return context.sync().then(() => {
      const transactionColumns = transactionsHeaderRange.values[0];

      const formattedTransactionsData = transactionsData.map(transactionRow => {
          const formattedRow = [];
          transactionColumns.forEach((column, index) => {
              formattedRow.push(transactionRow[index] || '');
          });
          return formattedRow;
      });

      accountsTable.rows.add(null, accountsData);
      transactionsTable.rows.add(null, formattedTransactionsData);
      
      return applyFormulasToTransactions(context, workbook); // Call the formula application function
  });
}

async function applyFormulasToTransactions(context, workbook) {
    try {
        const confSheet = workbook.worksheets.getItem('Conf');
        const transactionsSheet = workbook.worksheets.getItem('Transactions');

        // Load the Formulas table
        const formulasTable = confSheet.tables.getItem('Formulas');
        const formulaColumns = formulasTable.columns.load('items');
        await context.sync();

        // Load the Transactions table
        const transactionsTable = transactionsSheet.tables.getItem('Transactions');
        const transactionColumns = transactionsTable.columns.load('items');
        await context.sync();

        // Iterate over each formula in the Formulas table
        for (let i = 0; i < formulaColumns.items.length; i++) {
            const formulaColumn = formulaColumns.items[i];
            const formulaRange = formulaColumn.getDataBodyRange().load('values');
            await context.sync();

            const formula = formulaRange.values[0][0];
            if (formula) {
                const transactionColumn = transactionsTable.columns.getItem(formulaColumn.name);
                const transactionColumnRange = transactionColumn.getDataBodyRange();
                
                // Apply the formula to the entire column
                transactionColumnRange.formulas = [[`=${formula}`]];
            }
        }

        await context.sync();
    } catch (error) {
        console.error('Error applying formulas to transactions:', error);
    }
}

function createErrorCard(institutionName, errorCode, errorMessage) {
    const errorCard = createCard('error', institutionName, null, null, errorCode, errorMessage);
    document.getElementById('cardsContainer').appendChild(errorCard);
}

function createSuccessCard(institutionName, operation, transactionCount) {
    const successCard = createCard('success', institutionName, operation, transactionCount);
    document.getElementById('cardsContainer').appendChild(successCard);
}