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
                  sessionStorage.clear();
                  
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
  return Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItemOrNullObject('Accounts');
    await context.sync();

    if (sheet.isNullObject) {
      return [];
    }

    const accountsTable = sheet.tables.getItem('Accounts');
    const credentialIdColumn = accountsTable.columns.getItem('Credential ID');
    const nextCursorColumn = accountsTable.columns.getItem('Next Cursor');
    const credentialIdValues = credentialIdColumn.getDataBodyRange().load('values');
    const nextCursorValues = nextCursorColumn.getDataBodyRange().load('values');
    await context.sync();

    const uniquePairs = new Set();
    credentialIdValues.values.flat().forEach((credentialId, index) => {
      const cursor = nextCursorValues.values.flat()[index];
      if (cursor) {
        uniquePairs.add(`${credentialId}:${cursor}`);
      }
    });

    return Array.from(uniquePairs).join(',');
  }).catch(error => {
    console.error('Error getting cursors:', error);
    showToast('Failed to get cursors for transactions sync.', 'error');
    return '';
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
        let transactionsTableExists = false;

        return workbook.load('worksheets').context.sync()
            .then(() => {
                const transactionsSheet = workbook.worksheets.getItem('Transactions');
                const transactionsTable = transactionsSheet.tables.getItemOrNullObject('Transactions');
                
                transactionsTable.load('name');
                return context.sync()
                    .then(() => {
                        transactionsTableExists = true;
                    })
                    .catch(() => {
                        // Table doesn't exist, continue without setting the flag
                    });
            })
            .then(() => {
                if (!transactionsTableExists) {
                    return importTemplateSheets(context, workbook);
                }
            })
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
            .then(() => {
                if (!transactionsTableExists) {
                    return updateNamedRanges(context, workbook)
                        .then(() => applyFormulasToTransactions(context, workbook))
                        .then(() => recreatePivotTable(context));
                }
            })
            .catch(error => {
                console.error('Error syncing transactions:', error);
                createErrorCard('Sync', 'SYNC_ERROR', error.message); // Create error card for sync error
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
        createErrorCard('Excel', 'EXCEL_ERROR', error.message); // Create error card for Excel error
        showToast('An error occurred. Please try again.', 'error');
    });
}

function processTransactionData(context, workbook, data) {
    const banksWithErrors = new Set();

    const cardsContainer = document.getElementById('cardsContainer');
    while (cardsContainer.firstChild) {
        cardsContainer.removeChild(cardsContainer.firstChild);
    }

    if (data.banks) {
        data.banks.forEach(bank => {
            if (bank.error) {
                const errorCode = bank.error.error_code;
                const errorMessage = bank.error.error_message;
                createErrorCard(bank.institution_name, errorCode, errorMessage); // Create error card for each bank error
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
            createErrorCard('ProcessData', 'PROCESS_ERROR', error.message); // Create error card for processing error
            showToast('Failed to sync transactions. Please try again.', 'error');
        });
}

function importTemplateSheets(context, workbook) {
  return new Promise((resolve, reject) => {
      const sheets = workbook.worksheets;
      const sheetNames = ['Conf', 'Accounts', 'Transactions', 'Dashboard'];
      let existingSheets = [];
      
      sheets.load('items/name');
      
      context.sync().then(() => {
          sheets.items.forEach(sheet => {
              if (sheetNames.includes(sheet.name)) {
                  existingSheets.push(sheet.name);
              }
          });
          
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
                    account.type === 'credit' || account.type === 'loan' ? -account.balance : account.balance,
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
                        const jsDate = new Date(transaction.date);
                        const excelDate = jsDate.getTime() / (1000 * 60 * 60 * 24) + 25569 + (jsDate.getTimezoneOffset() / (60 * 24));

                        const transactionRow = [
                            account.plaid_account_id,
                            transaction.action,
                            -1 * transaction.amount,
                            categories,
                            excelDate,
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

    accountsTable.clearFilters();
    transactionsTable.clearFilters();

    const accountsRange = accountsTable.getDataBodyRange().load('values');
    const transactionsRange = transactionsTable.getDataBodyRange().load('values');

    return context.sync().then(() => {
        const existingAccounts = accountsRange.values.reduce((map, row) => {
            map[row[6]] = row;
            return map;
        }, {});

        const existingTransactions = transactionsRange.values.reduce((map, row) => {
            map[row[10]] = row;
            return map;
        }, {});

        const newAccountsData = [];
        const newTransactionsData = [];

        accountsData.forEach(accountRow => {
            const plaidAccountId = accountRow[6];
            if (existingAccounts[plaidAccountId]) {
                accountsTable.rows.getItemAt(existingAccounts[plaidAccountId]._rowIndex).delete();
            }
            newAccountsData.push(accountRow);
        });

        transactionsData.forEach(transactionRow => {
            const transactionId = transactionRow[10];
            if (existingTransactions[transactionId]) {
                transactionsTable.rows.getItemAt(existingTransactions[transactionId]._rowIndex).delete();
            }
            newTransactionsData.push(transactionRow);
        });

        const transactionsHeaderRange = transactionsTable.getHeaderRowRange().load('values');

        return context.sync().then(() => {
            const transactionColumns = transactionsHeaderRange.values[0];

            const formattedTransactionsData = newTransactionsData.map(transactionRow => {
                const formattedRow = [];
                transactionColumns.forEach((column, index) => {
                    formattedRow.push(transactionRow[index] || '');
                });
                return formattedRow;
            });

            accountsTable.rows.add(null, newAccountsData);
            transactionsTable.rows.add(null, formattedTransactionsData);

            return applyFormulasToTransactions(context, workbook);
        }).catch(error => {
            console.error('Error in insertTransactionData:', error);
            showToast('Failed to insert transaction data. Please try again.', 'error');
        });
    });
}


async function applyFormulasToTransactions(context, workbook) {
    try {
        console.log('Starting to apply formulas to transactions...');

        const confSheet = workbook.worksheets.getItem('Conf');
        await confSheet.load('name').context.sync();

        const formulasTable = confSheet.tables.getItem('Formulas');
        const formulaColumns = formulasTable.columns.load('items');
        await context.sync();

        const transactionsSheet = workbook.worksheets.getItem('Transactions');
        await transactionsSheet.load('name').context.sync();

        const transactionsTable = transactionsSheet.tables.getItem('Transactions');
        const transactionColumns = transactionsTable.columns.load('items');
        await context.sync();

        const formulaRange = formulasTable.getDataBodyRange().load('values');
        await context.sync();

        for (let i = 0; i < formulaRange.values.length; i++) {
            const [columnName, formula] = formulaRange.values[i];

            if (formula) {
                const transactionColumn = transactionsTable.columns.getItem(columnName);
                const transactionColumnRange = transactionColumn.getDataBodyRange();
                await transactionColumnRange.load('rowCount').context.sync();

                const rowCount = transactionColumnRange.rowCount;

                const isArrayFormula = formula.includes("XLOOKUP") || formula.includes("MATCH") || formula.includes("INDEX") || formula.includes("SUMIFS") || formula.includes("AVERAGEIFS");

                if (isArrayFormula) {
                    transactionColumnRange.formulas = Array(rowCount).fill([`=${formula}`]);
                } else {
                    transactionColumnRange.formulas = Array(rowCount).fill([`=${formula}`]);
                }

                await context.sync();
            }
        }
        console.log('Formulas applied to all columns successfully');

        // Set the value of the named cell "Sel_Month" to the first cell of the named range "Unique_Months"
        const dashboardSheet = workbook.worksheets.getItem('Dashboard');
        const confD1Range = confSheet.getRange('D1');
        const dashboardI1Range = dashboardSheet.getRange('I1');

        await confD1Range.load('values');
        await context.sync();

        const confD1Value = confD1Range.values[0][0];
        dashboardI1Range.values = [[confD1Value]];

        // Get the Named Range 'Sel_Month' and set its formula
        const selMonthNamedItem = workbook.names.getItem('Sel_Month');
        selMonthNamedItem.formula = '=Dashboard!$I$1';

        await context.sync();
    
        console.log('Cell I1 in "Dashboard" set to the value of cell D1 in "Conf" successfully');
        
        // Hide the "Conf" sheet
        confSheet.visibility = Excel.SheetVisibility.hidden;
        await context.sync();
        
    } catch (error) {
        console.error('Error applying formulas to transactions:', error);
    }
}

async function updateNamedRanges(context, workbook) {
    try {
        console.log('Starting to update named ranges...');

        const confSheet = workbook.worksheets.getItem('Conf');
        await confSheet.load('name').context.sync();

        const namesTable = confSheet.tables.getItem('Names');
        const namesDataRange = namesTable.getDataBodyRange().load('values');
        await context.sync();

        for (let i = 0; i < namesDataRange.values.length; i++) {
            const [name, formula] = namesDataRange.values[i];

            const cleanFormula = formula.startsWith('=') ? formula : `=${formula}`;

            let namedRange = workbook.names.getItemOrNullObject(name);
            await context.sync();

            if (namedRange.isNullObject) {
                workbook.names.add(name, cleanFormula);
            } else {
                namedRange.formula = cleanFormula;
            }

            await context.sync();
        }

        console.log('Named ranges updated successfully');
    } catch (error) {
        console.error('Error updating named ranges:', error);
    }
}

async function recreatePivotTable(context) {
    try {
      console.log('Starting to recreate pivot table...');
  
      // Delete the existing PivotTable named "Summary"
      const dashboardSheet = context.workbook.worksheets.getItem("Dashboard");
      const pivotTable = dashboardSheet.pivotTables.getItem("Summary");
      pivotTable.delete();
      await context.sync();
  
      // Create a new PivotTable named "Summary" on sheet "Dashboard" at cell A4
      const newPivotTable = dashboardSheet.pivotTables.add("Summary", "Transactions", "E2");
      newPivotTable.columnGrandTotals = false;
      newPivotTable.rowGrandTotals = false;
  
      // Add row hierarchies
      newPivotTable.rowHierarchies.add(newPivotTable.hierarchies.getItem("Custom Category"));
      newPivotTable.rowHierarchies.add(newPivotTable.hierarchies.getItem("Name"));
  
      // Add data hierarchies and set summarization
      const averageHierarchy = newPivotTable.hierarchies.getItem("6M AVG");
      const budgetHierarchy = newPivotTable.hierarchies.getItem("Budget");
  
      const averageField = newPivotTable.dataHierarchies.add(averageHierarchy);
      averageField.summarizeBy = Excel.AggregationFunction.max;
      averageField.numberFormat = "$#,##0";
      averageField.name = "6M Average";
  
      const budgetField = newPivotTable.dataHierarchies.add(budgetHierarchy);
      budgetField.summarizeBy = Excel.AggregationFunction.max;
      budgetField.numberFormat = "$#,##0";
      budgetField.name = "Budget";

      // Delete the existing PivotTable named "Balances"
        const pivotTableB = dashboardSheet.pivotTables.getItem("Balances");
        pivotTableB.delete();
        await context.sync();
        
      // Create the 'Balances' pivot table
        const balancesPivotTable = dashboardSheet.pivotTables.add("Balances", "Accounts", "A2");
        balancesPivotTable.columnGrandTotals = true;
        balancesPivotTable.rowGrandTotals = true;

        // Add row hierarchies
        balancesPivotTable.rowHierarchies.add(balancesPivotTable.hierarchies.getItem("Institution Name"));
        balancesPivotTable.rowHierarchies.add(balancesPivotTable.hierarchies.getItem("Type"));
        balancesPivotTable.rowHierarchies.add(balancesPivotTable.hierarchies.getItem("Name"));

        // Add data hierarchies and set summarization
        const numberField = balancesPivotTable.dataHierarchies.add(balancesPivotTable.hierarchies.getItem("Mask"));
        numberField.summarizeBy = Excel.AggregationFunction.max;
        numberField.name = "Number";

        const balanceField = balancesPivotTable.dataHierarchies.add(balancesPivotTable.hierarchies.getItem("Balance"));
        balanceField.summarizeBy = Excel.AggregationFunction.sum;
        balanceField.numberFormat = "#,##0.00";
        balanceField.name = "Balance";

      await context.sync();
  
      console.log('Pivot table recreated successfully');
    } catch (error) {
      console.error('Error recreating pivot table:', error);
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
