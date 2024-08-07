// dashboard.js
console.log("Dashboard script loaded v3");

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

$('.sync-transactions-btn').click(function () {
    syncTransactions();
});

Office.onReady(() => {
    $(document).ready(function () {
        $('.open-dashboard-btn').click(function () {
            const token = localStorage.getItem('authToken');
            if (token) {
                const dashboardUrl = window.appConfig.backEndUrl + '/dashboard';
                const windowFeatures = 'toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=1200,height=800';
                window.open(dashboardUrl, '_blank', windowFeatures);
            } else {
                console.error('User not authenticated');
                showToast('Please log in to access the dashboard.', 'warning');
            }
        });

        $('#confirmLogout').click(function () {
            console.log("Confirm Logout button clicked");

            fetch(window.appConfig.backEndUrl + '/logout', {
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
let isFirstRun = false; // Global flag to track the first run

function syncTransactions() {
    if (isSyncing) {
        console.log('Sync is already in progress');
        return;
    }
    isSyncing = true;
    console.log('Syncing commenced');
    const token = localStorage.getItem('authToken');
    if (!token) {
        console.error('User not authenticated');
        showToast('Please log in to sync transactions.', 'warning');
        isSyncing = false;
        console.log('Syncing aborted: user not authenticated');
        return;
    }
    console.log('User already authenticated');
    
    const loader = document.createElement('div');
    loader.className = 'loader';
    document.body.appendChild(loader);
    
    function updateLoaderMessage(message) {
        loader.innerHTML = `<i class="fas fa-spinner fa-spin"></i><br>${message}`;
    }
    
    updateLoaderMessage('Importing Template');
    
    Excel.run(context => {
        const workbook = context.workbook;
        let transactionsTableExists = false;
        return workbook.load('worksheets').context.sync()
            .then(() => {
                //console.log('Worksheets in the user workbook:', workbook.worksheets.items.map(ws => ws.name));
                const transactionsSheet = workbook.worksheets.getItem('Transactions');
                const transactionsTable = transactionsSheet.tables.getItemOrNullObject('Transactions');
                
                transactionsTable.load('name');
                return context.sync()
                    .then(() => {
                        console.log('Transactions table loaded:', transactionsTable.name);
                        transactionsTableExists = true;
                    })
                    .catch((error) => {
                        console.log('Transactions table does not exist:', error);
                    });
            })
            .then(() => {
                if (!transactionsTableExists) {
                    return importTemplateSheetsFromJSON(context, workbook);
                }
            })
            .then(() => {
                updateLoaderMessage('Requesting Transactions');
                console.log('Getting cursors');
                return getCursors();
            })
            .then(cursors => {
                //console.log('Cursors retrieved:', cursors);
                return fetch(window.appConfig.backEndUrl + '/sync', {
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
                    console.log('Sync response failed:', response.status, response.statusText);
                    throw new Error('Failed to sync transactions');
                }
            })
            .then(data => {
                updateLoaderMessage('Updating Tables');
                console.log('Transaction data retrieved:', data);
                return processTransactionData(context, workbook, data);
            })
            .then(() => {
                updateLoaderMessage('Refreshing Formulas');
                return applyFormulasToTransactions(context, workbook);
            })
            .then(() => {
                if (isFirstRun) {
                    updateLoaderMessage('Applying Pivot Table Settings');
                    return createPivotTables(context, workbook).then(() => {
                        isFirstRun = false;
                    });
                }
            })
            .then(() => {
                return refreshAllPivotTables(context, workbook);
            })
            .catch(error => {
                console.error('Error syncing transactions:', error);
                createErrorCard('Sync', 'SYNC_ERROR', error.message);
                showToast('Failed to sync transactions. Please try again.', 'error');
            })
            .finally(() => {
                isSyncing = false;
                if (loader) {
                    document.body.removeChild(loader);
                }
                console.log('Syncing process completed, cleaning up.');
            });
    }).catch(error => {
        console.error('Error in Excel.run:', error);
        createErrorCard('Excel', 'EXCEL_ERROR', error.message);
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

async function importTemplateSheetsFromJSON(context, workbook) {
    try {
        const response = await fetch(`${window.appConfig.frontEndUrl}/assets/template.json`);
        if (!response.ok) {
            throw new Error('Failed to fetch JSON template');
        }
        const template = await response.json();
        console.log('JSON template loaded:', template);

        const tablesToProcess = [];
        //const pivotTablesToProcess = [];
        const otherCellsToProcess = [];
        const cellsToProcess = [];
        const conditionalFormattingToProcess = [];
        const dataValidationsToProcess = [];

        for (const sheet of template.Sheets) {
            let excelSheet = workbook.worksheets.getItemOrNullObject(sheet.Name);
            await context.sync();

            if (excelSheet.isNullObject) {
                excelSheet = workbook.worksheets.add(sheet.Name);
                //await context.sync();
                console.log(`Worksheet ${sheet.Name} created`);
            } else {
                console.log(`Worksheet ${sheet.Name} already exists`);
            }

            await importListObjects(context, excelSheet, sheet.ListObjects, tablesToProcess);

            //if (sheet.PivotTables) {
            //    pivotTablesToProcess.push({ sheet: excelSheet, pivotTables: sheet.PivotTables });
            //}
 
            if (sheet.OtherCells) {
                otherCellsToProcess.push({ sheet: excelSheet, otherCells: sheet.OtherCells });
            }

            if (sheet.Cells) {
                cellsToProcess.push({ sheet: excelSheet, cells: sheet.Cells });
            }            

            if (sheet.ConditionalFormatting) {
                conditionalFormattingToProcess.push({ sheet: excelSheet, conditionalFormatting: sheet.ConditionalFormatting });
            }   

            if (sheet.DataValidations) {
                dataValidationsToProcess.push({ sheet: excelSheet, dataValidations: sheet.DataValidations });
            }
        }

        if (template.CustomNamedRanges) {
            await importCustomNamedRanges(context, workbook, template.CustomNamedRanges);
        }

        await processTableFormulas(context, tablesToProcess);

        //await importPivotTables(context, workbook, pivotTablesToProcess);

        await importOtherCells(context, otherCellsToProcess);

        await importCells(context, cellsToProcess);        

        await importConditionalFormatting(context, conditionalFormattingToProcess);

        await importDataValidations(context, dataValidationsToProcess);
        
        //await context.sync();
        console.log('Sheets, tables, and pivot tables from JSON template imported successfully.');
    } catch (error) {
        console.error('Error importing sheets from JSON template:', error);
        showToast('Failed to import template. Please try again.', 'error');
    }
}

async function importCustomNamedRanges(context, workbook, namedRanges) {
    try {
        for (const range of namedRanges) {
            const name = range.Name;
            const refersTo = range.RefersTo;

            const existingName = workbook.names.getItemOrNullObject(name);
            await context.sync();

            if (existingName.isNullObject) {
                workbook.names.add(name, refersTo);
                console.log(`Named range ${name} added.`);
            } else {
                existingName.delete();
                await context.sync();
                workbook.names.add(name, refersTo);
                console.log(`Named range ${name} updated with new refersTo value.`);
            }
        }
        await context.sync();
        console.log('CustomNamedRanges imported successfully.');
    } catch (error) {
        console.error('Error importing CustomNamedRanges:', error);
        showToast('Failed to import named ranges. Please try again.', 'error');
    }
}


async function importOtherCells(context, sheets) {
    try {
        if (!sheets || sheets.length === 0) {
            console.log('No sheets to process for OtherCells.');
            return;
        }

        for (const sheetObj of sheets) {
            const sheet = sheetObj.sheet;
            const otherCells = sheetObj.otherCells;

            sheet.load('name');
            await context.sync();

            if (!otherCells || otherCells.length === 0) {
                console.log(`No OtherCells to process for sheet ${sheet.name}.`);
                continue;
            }

            for (const cell of otherCells) {
                const range = sheet.getRange(cell.Address);

                const addressParts = cell.Address.split(':');
                const startAddress = addressParts[0];
                const endAddress = addressParts[1];

                const startRow = parseInt(startAddress.match(/\d+/)[0]);
                const endRow = parseInt(endAddress.match(/\d+/)[0]);
                const numRows = endRow - startRow + 1;

                const startColumn = startAddress.match(/[A-Z]+/)[0];
                const endColumn = endAddress.match(/[A-Z]+/)[0];
                const numColumns = endColumn.charCodeAt(0) - startColumn.charCodeAt(0) + 1;

                if (cell.Formula) {
                    const formulas = Array(numRows).fill(Array(numColumns).fill(cell.Formula));
                    range.formulasR1C1 = formulas;
                }

                if (cell.FillColor) {
                    range.format.fill.color = cell.FillColor;
                }

                if (cell.NumberFormat) {
                    range.numberFormat = [[cell.NumberFormat]];
                }

                if (cell.Font) {
                    const font = range.format.font;
                    if (cell.Font.Size) font.size = cell.Font.Size;
                    if (cell.Font.Color) font.color = cell.Font.Color;
                    if (cell.Font.Bold !== undefined) font.bold = cell.Font.Bold;
                    if (cell.Font.Italic !== undefined) font.italic = cell.Font.Italic;
                }
            }
        }
        await context.sync();
        console.log('OtherCells imported successfully.');
    } catch (error) {
        console.error('Error importing OtherCells:', error);
        showToast('Failed to import other cells. Please try again.', 'error');
    }
}

async function importCells(context, sheets) {
    try {
        if (!sheets || sheets.length === 0) {
            console.log('No sheets to process for Cells.');
            return;
        }

        for (const sheetObj of sheets) {
            const sheet = sheetObj.sheet;
            const cells = sheetObj.cells;

            sheet.load('name');
            await context.sync();

            if (!cells || cells.length === 0) {
                console.log(`No Cells to process for sheet ${sheet.name}.`);
                continue;
            }

            for (const cell of cells) {
                const range = sheet.getRange(cell.Address);
                if (cell.Value !== undefined) {
                    range.values = [[cell.Value]];
                }

                if (cell.FillColor) {
                    range.format.fill.color = cell.FillColor;
                }

                if (cell.NumberFormat) {
                    range.numberFormat = [[cell.NumberFormat]];
                }

                if (cell.Font) {
                    const font = range.format.font;
                    if (cell.Font.Size) font.size = cell.Font.Size;
                    if (cell.Font.Color) font.color = cell.Font.Color;
                    if (cell.Font.Bold !== undefined) font.bold = cell.Font.Bold;
                    if (cell.Font.Italic !== undefined) font.italic = cell.Font.Italic;
                }
            }
        }
        await context.sync();
        console.log('Cells imported successfully.');
    } catch (error) {
        console.error('Error importing Cells:', error);
        showToast('Failed to import cells. Please try again.', 'error');
    }
}

async function importConditionalFormatting(context, sheetsToProcess) {
    try {
        if (!sheetsToProcess || sheetsToProcess.length === 0) {
            console.log('No sheets to process for ConditionalFormatting.');
            return;
        }

        for (const sheetObj of sheetsToProcess) {
            const sheet = sheetObj.sheet;
            const conditionalFormatting = sheetObj.conditionalFormatting;

            sheet.load('name');
            await context.sync();

            if (!conditionalFormatting || conditionalFormatting.length === 0) {
                console.log(`No ConditionalFormatting to process for sheet ${sheet.name}.`);
                continue;
            }

            console.log(`Processing ConditionalFormatting for sheet ${sheet.name}`);

            for (const cf of conditionalFormatting) {
                const range = sheet.getRange(cf.AppliesTo);
                let conditionalFormat;

                // Handle custom formula (Type 2)
                conditionalFormat = range.conditionalFormats.add(Excel.ConditionalFormatType.custom);
                conditionalFormat.custom.rule.formula = cf.Formula;

                if (cf.Interior) {
                    const interior = conditionalFormat.custom.format.fill;
                    if (cf.Interior.Color !== undefined) {
                        // Convert number to hex color string
                        interior.color = cf.Interior.Color;
                    }
                    if (cf.Interior.Pattern !== undefined) {
                        interior.pattern = cf.Interior.Pattern;
                    }
                }

                if (cf.Font) {
                    const font = conditionalFormat.custom.format.font;
                    if (cf.Font.Name) {
                        font.name = cf.Font.Name;
                    }
                    if (cf.Font.Size) {
                        font.size = cf.Font.Size;
                    }
                    if (cf.Font.Color) {
                        font.color = cf.Font.Color;
                    }
                    if (cf.Font.Bold !== undefined) {
                        font.bold = cf.Font.Bold;
                    }
                    if (cf.Font.Italic !== undefined) {
                        font.italic = cf.Font.Italic;
                    }
                }
            }

            console.log(`ConditionalFormatting processed for sheet ${sheet.name}`);
        }

        await context.sync();
        console.log('All ConditionalFormatting imported successfully.');
    } catch (error) {
        console.error('Error importing ConditionalFormatting:', error);
        showToast('Failed to import conditional formatting. Please try again.', 'error');
    }
}

async function importListObjects(context, excelSheet, listObjects, tablesToProcess) {
    try {
        for (const listObject of listObjects) {
            const table = excelSheet.tables.getItemOrNullObject(listObject.Name);
            await context.sync();

            if (table.isNullObject) {
                isFirstRun = true;
                console.log(`Creating table ${listObject.Name} at ${listObject.StartingCell}`);
                // Calculate the range for the header
                const startCell = listObject.StartingCell.replace('$', '');
                const startColumn = startCell.match(/[A-Z]+/)[0];
                const startRow = parseInt(startCell.match(/\d+/)[0]);
                const numColumns = listObject.Columns.length;
                const endColumn = String.fromCharCode(startColumn.charCodeAt(0) + numColumns - 1);
                const range = `${startColumn}${startRow}:${endColumn}${startRow}`;

                const headers = [listObject.Columns.map(column => column.Header)];
                const newTable = excelSheet.tables.add(range, true /*hasHeaders*/);
                newTable.name = listObject.Name;
                newTable.style = listObject.ColorStyle;

                newTable.getHeaderRowRange().values = headers;
                await context.sync();
                console.log(`Table ${listObject.Name} created with headers: ${headers}`);

                // Store the table and listObject for later processing
                tablesToProcess.push({ table: newTable, listObject });

                // Set column widths if provided
                for (let i = 0; i < listObject.Columns.length; i++) {
                    const column = listObject.Columns[i];
                    const tableColumn = newTable.columns.getItemAt(i);

                    if (column.Width) {
                        tableColumn.getRange().format.columnWidth = column.Width * 5;
                    }
                }
            } else {
                console.log(`Table ${listObject.Name} already exists.`);
            }
        }
    } catch (error) {
        console.error('Error importing list objects:', error);
        throw error;
    }
}

async function processTableFormulas(context, tablesToProcess) {
    try {
        // Process the tables to add initial rows with formulas and then remove them
        for (const { table, listObject } of tablesToProcess) {
            const initialRow = listObject.Columns.map(column => column.Formula || "");
            if (initialRow.some(cell => cell !== "")) {
                //console.log(`Trying to insert row with values ${initialRow}`);
                table.rows.add(null /*add rows to the end of the table*/, [initialRow]);
                //await context.sync();
                //console.log(`Initial row with formulas added to table ${listObject.Name}`);

                // Remove the row after setting the formulas
                table.rows.getItemAt(0).delete();
                //await context.sync();
                //console.log(`Initial row with formulas removed from table ${listObject.Name}`);
            }

            // Add rows if there are any
            if (listObject.Rows.length > 0) {
                table.rows.add(null /*add rows to the end of the table*/, listObject.Rows);
                //await context.sync();
                //console.log(`Rows added to table ${listObject.Name}`);
            }
        }
        await context.sync();
    } catch (error) {
        console.error('Error processing table formulas:', error);
        throw error;
    }
}

async function importDataValidations(context, sheets) {
    try {
        if (!sheets || sheets.length === 0) {
            console.log('No sheets to process for DataValidations.');
            return;
        }

        for (const sheetObj of sheets) {
            const sheet = sheetObj.sheet;
            const dataValidations = sheetObj.dataValidations;

            sheet.load('name');
            await context.sync();

            if (!dataValidations || dataValidations.length === 0) {
                console.log(`No DataValidations to process for sheet ${sheet.name}.`);
                continue;
            }

            for (const validation of dataValidations) {
                const range = sheet.getRange(validation.Address);
                const rule = {};

                if (validation.Type === "3") { // List type
                    rule.list = {
                        inCellDropDown: true,
                        source: validation.Formula1
                    };
                }
                // Add other types here as needed

                range.dataValidation.rule = rule;

                range.dataValidation.prompt = {
                    showPrompt: validation.ShowInputMessage,
                    title: validation.InputTitle,
                    message: validation.InputMessage
                };

                range.dataValidation.errorAlert = {
                    showAlert: validation.ShowErrorMessage,
                    title: validation.ErrorTitle,
                    message: validation.ErrorMessage,
                    style: Excel.DataValidationAlertStyle.stop
                };

                await context.sync();
            }
        }
        await context.sync();
        console.log('DataValidations imported successfully.');
    } catch (error) {
        console.error('Error importing DataValidations:', error);
        showToast('Failed to import data validations. Please try again.', 'error');
    }
}

async function createPivotTables(context, workbook) {
    try {
        const aggregationMapping = {
            "Sum": Excel.AggregationFunction.sum,
            "Count": Excel.AggregationFunction.count,
            "Average": Excel.AggregationFunction.average,
            "Max": Excel.AggregationFunction.max,
            "Min": Excel.AggregationFunction.min,
            "Product": Excel.AggregationFunction.product,
            "CountNumbers": Excel.AggregationFunction.countNumbers,
            "StandardDeviation": Excel.AggregationFunction.standardDeviation,
            "StandardDeviationP": Excel.AggregationFunction.standardDeviationP,
            "Variance": Excel.AggregationFunction.variance,
            "VarianceP": Excel.AggregationFunction.varianceP,
            "Automatic": Excel.AggregationFunction.automatic,
        };

        const showAsMapping = {
            "None": Excel.ShowAsCalculation.none,
            "PercentOfGrandTotal": Excel.ShowAsCalculation.percentOfGrandTotal,
            "PercentOfRowTotal": Excel.ShowAsCalculation.percentOfRowTotal,
            "PercentOfColumnTotal": Excel.ShowAsCalculation.percentOfColumnTotal,
            "PercentOfParentRowTotal": Excel.ShowAsCalculation.percentOfParentRowTotal,
            "PercentOfParentColumnTotal": Excel.ShowAsCalculation.percentOfParentColumnTotal,
            "PercentOfParentTotal": Excel.ShowAsCalculation.percentOfParentTotal,
            "PercentOf": Excel.ShowAsCalculation.percentOf,
            "RunningTotal": Excel.ShowAsCalculation.runningTotal,
            "PercentRunningTotal": Excel.ShowAsCalculation.percentRunningTotal,
            "DifferenceFrom": Excel.ShowAsCalculation.differenceFrom,
            "PercentDifferenceFrom": Excel.ShowAsCalculation.percentDifferenceFrom,
            "RankAscending": Excel.ShowAsCalculation.rankAscending,
            "RankDescending": Excel.ShowAsCalculation.rankDescending,
            "Index": Excel.ShowAsCalculation.index,
        };   

        const response = await fetch(`${window.appConfig.frontEndUrl}/assets/template.json`);
        if (!response.ok) {
            throw new Error('Failed to fetch JSON template');
        }
        const template = await response.json();

        const worksheets = workbook.worksheets.load('items');
        await context.sync();
        
        console.log('Worksheets loaded:', worksheets.items.map(sheet => sheet.name));

        for (const sheet of template.Sheets) {
            const excelSheet = workbook.worksheets.getItem(sheet.Name);
            await excelSheet.load('pivotTables/items').context.sync();
            console.log(`Processing sheet: ${sheet.Name}`);

            for (const pivotTable of sheet.PivotTables) {
                // Create new PivotTable
                const newPivotTable = excelSheet.pivotTables.add(pivotTable.Name, pivotTable.SourceData, pivotTable.StartingCell);
                newPivotTable.columnGrandTotals = pivotTable.ColumnGrandTotals;
                newPivotTable.rowGrandTotals = pivotTable.RowGrandTotals;
                
                // Add row fields
                for (const rowField of pivotTable.RowFields) {
                    const rowHierarchy = newPivotTable.hierarchies.getItem(rowField.Name);
                    const newRowField = newPivotTable.rowHierarchies.add(rowHierarchy);
                    newRowField.name = rowField.CustomName;
                    newRowField.subtotals = rowField.Subtotals;
                }

                // Add column fields
                for (const columnField of pivotTable.ColumnFields) {
                    const columnHierarchy = newPivotTable.hierarchies.getItem(columnField.Name);
                    const newColumnField = newPivotTable.columnHierarchies.add(columnHierarchy);
                    newColumnField.name = columnField.CustomName;
                    newColumnField.subtotals = columnField.Subtotals;
                }

                // Add data fields
                for (const valueField of pivotTable.ValueFields) {
                    const dataHierarchy = newPivotTable.hierarchies.getItem(valueField.Name);
                    const newValueField = newPivotTable.dataHierarchies.add(dataHierarchy);
                    newValueField.summarizeBy = aggregationMapping[valueField.SummarizedBy] || Excel.AggregationFunction.automatic;
                    newValueField.numberFormat = valueField.NumberFormat;
                    newValueField.name = valueField.CustomName;
                }

                await context.sync();
                console.log(`Recreated pivot table: ${pivotTable.Name}`);
            }
        }

        console.log('All pivot tables recreated successfully.');
    } catch (error) {
        console.error('Error recreating pivot tables:', error);
        createErrorCard('PivotTable', 'PIVOT_TABLE_ERROR', error.message);
        showToast('Failed to recreate pivot tables. Please try again.', 'error');
    }
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
            if (newAccountsData.length > 0) {
                accountsTable.rows.add(null, newAccountsData);
                //console.log('Just added Accounts and ready to add these transactions: ', newTransactionsData);
            }

            if (newTransactionsData.length > 0) {
                const transactionColumns = transactionsHeaderRange.values[0];
                const formattedTransactionsData = newTransactionsData.map(transactionRow => {
                    const formattedRow = [];
                    transactionColumns.forEach((column, index) => {
                        formattedRow.push(transactionRow[index] || '');
                    });
                    return formattedRow;
                });

                transactionsTable.rows.add(null, formattedTransactionsData);
            }
        }).catch(error => {
            console.error('Error in insertTransactionData:', error);
            showToast('Failed to insert transaction data. Please try again.', 'error');
        });
    });
}


async function applyFormulasToTransactions(context, workbook) {
    try {
        console.log('Starting to apply formulas to transactions...');

        const response = await fetch(`${window.appConfig.frontEndUrl}/assets/template.json`);
        if (!response.ok) {
            throw new Error('Failed to fetch JSON template');
        }
        const template = await response.json();

        for (const sheet of template.Sheets) {
            const excelSheet = workbook.worksheets.getItem(sheet.Name);
            await excelSheet.load('name').context.sync();

            for (const listObject of sheet.ListObjects) {
                const table = excelSheet.tables.getItemOrNullObject(listObject.Name);
                await table.load('name, isNullObject').context.sync();

                if (!table.isNullObject) {
                    const columns = table.columns.load('items');
                    await context.sync();

                    for (let i = 0; i < listObject.Columns.length; i++) {
                        const templateColumn = listObject.Columns[i];
                        const formula = templateColumn.Formula;

                        if (formula) {
                            const column = columns.items[i];
                            const columnRange = column.getDataBodyRange();
                            await columnRange.load('values, rowCount').context.sync();

                            // Apply formula only if the column is empty
                            const isEmpty = columnRange.values.every(row => row.every(cell => cell === null || cell === ""));
                            if (isEmpty) {
                                const rowCount = columnRange.rowCount;
                                const formulas = Array(rowCount).fill([formula]);
                                //console.log(`Applying formula to column: ${templateColumn.Header} with row count: ${rowCount}`);
                                columnRange.formulas = formulas;
                                await context.sync();
                            } else {
                                console.log(`Skipping formula for column: ${templateColumn.Header} as it is not empty.`);
                            }
                        }
                    }
                }
            }
        }

        console.log('Formulas applied to all relevant tables successfully.');
    } catch (error) {
        console.error('Error applying formulas to transactions:', error);
        showToast('Failed to apply formulas. Please try again.', 'error');
    }
}

async function refreshAllPivotTables(context, workbook) {
    try {
        const worksheets = workbook.worksheets.load('items');
        await context.sync();

        for (const sheet of worksheets.items) {
            const pivotTables = sheet.pivotTables.load('items');
            await context.sync();

            for (const pivotTable of pivotTables.items) {
                pivotTable.refresh();
            }

            console.log(`Pivot tables in sheet ${sheet.name} refreshed.`);
        }

        await context.sync();
        console.log('All pivot tables refreshed successfully.');
    } catch (error) {
        console.error('Error refreshing pivot tables:', error);
        showToast('Failed to refresh pivot tables. Please try again.', 'error');
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
