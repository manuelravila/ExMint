// dashboard.js
console.log("Dashboard script loaded v3.23");

// Initially hide the cards container
const cardsContainer = document.getElementById('cardsContainer');
cardsContainer.style.display = 'none';

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
    
    Excel.run(async (context) => {
        const workbook = context.workbook;
        try {
            await importTemplateSheetsFromJSON(context, workbook);
            updateLoaderMessage('Requesting Transactions');
            console.log('Getting cursors...');
            const cursors = await getCursors();
            const response = await fetch(window.appConfig.backEndUrl + '/sync', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                    'X-Request-Source': 'Excel-Add-In',
                    'x-user-token': token,
                    'cursors': cursors
                }
            });

            if (response.ok) {
                console.log('Sync response OK');
                const data = await response.json();
                updateLoaderMessage('Updating Tables');
                await processTransactionData(context, workbook, data);
                updateLoaderMessage('Refreshing Formulas');
                await applyFormulasToTransactions(context, workbook);

                if (isFirstRun) {
                    updateLoaderMessage('Applying Pivot Table Settings');
                    await createPivotTables(context, workbook);
                    isFirstRun = false;
                }

                await refreshAllPivotTables(context, workbook);

                // **Activate the 'Dashboard' sheet**
                updateLoaderMessage('Finalizing');
                const dashboardSheet = workbook.worksheets.getItem('Dashboard');
                dashboardSheet.activate();
                await context.sync();
                console.log('Dashboard sheet activated.');
            } else {
                console.log('Sync response failed:', response.status, response.statusText);
                throw new Error('Failed to sync transactions');
            }
        } catch (error) {
            console.error('Error syncing transactions:', error);
            createErrorCard('Sync', 'SYNC_ERROR', error.message);
            showToast('Failed to sync transactions. Please try again.', 'error');
        } finally {
            isSyncing = false;
            if (loader) {
                document.body.removeChild(loader);
            }
            console.log('Syncing process completed, cleaning up.');
        }
    }).catch(error => {
        console.error('Error in Excel.run:', error);
        createErrorCard('Excel', 'EXCEL_ERROR', error.message);
        showToast('An error occurred. Please try again.', 'error');
    });
}

function processTransactionData(context, workbook, data) {
    const credentialsWithErrors = new Set();

    const cardsContainer = document.getElementById('cardsContainer');
    if (cardsContainer) {
        while (cardsContainer.firstChild) {
            cardsContainer.removeChild(cardsContainer.firstChild);
        }
    } else {
        console.error('cardsContainer not found');
        return;
    }

    if (data.banks) {
        data.banks.forEach(bank => {
            if (bank.error) {
                const errorCode = bank.error.error_code;
                const errorMessage = bank.error.error_message;
                createErrorCard(bank.institution_name, errorCode, errorMessage, bank.credential_id);
                credentialsWithErrors.add(bank.credential_id);
            } else {
                const transactionCount = bank.accounts.reduce((total, account) => total + (account.transactions ? account.transactions.length : 0), 0);
                createSuccessCard(bank.institution_name, bank.operation, transactionCount);
            }
        });
    }

    return insertTransactionData(context, workbook, data, credentialsWithErrors)
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
        const otherCellsToProcess = [];
        const cellsToProcess = [];
        const conditionalFormattingToProcess = [];
        const dataValidationsToProcess = [];
        const notesToProcess = []; 

        for (const sheet of template.Sheets) {
            let excelSheet = workbook.worksheets.getItemOrNullObject(sheet.Name);
            await context.sync();

            if (excelSheet.isNullObject) {
                excelSheet = workbook.worksheets.add(sheet.Name);
                await context.sync();
                console.log(`Worksheet ${sheet.Name} created`);
            } else {
                console.log(`Worksheet ${sheet.Name} already exists`);
            }

            await importListObjects(context, excelSheet, sheet.ListObjects, tablesToProcess);

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

            if (sheet.Notes) {
                notesToProcess.push({ sheet: excelSheet, notes: sheet.Notes }); 
              }
        }

        if (template.CustomNamedRanges) {
            await importCustomNamedRanges(context, workbook, template.CustomNamedRanges);
        }

        await importOtherCells(context, otherCellsToProcess);
        await importCells(context, cellsToProcess);        
        await importConditionalFormatting(context, conditionalFormattingToProcess);
        await importDataValidations(context, dataValidationsToProcess);
        await importNotes(context, workbook, notesToProcess);
        
        console.log('Sheets, tables, and pivot tables from JSON template imported successfully.');
    } catch (error) {
        console.error('Error importing sheets from JSON template:', error);
        showToast('Failed to import template. Please try again.', 'error');
    }
}

async function importNotes(context, workbook, notesToProcess) {
    if (!notesToProcess || notesToProcess.length === 0) {
        console.log('No Notes to process.');
        return;
    }

    for (const sheetObj of notesToProcess) {
        const sheet = sheetObj.sheet;
        const notes = sheetObj.notes;

        sheet.load('name');
        await context.sync();

        if (!notes || notes.length === 0) {
            console.log(`No Notes to process for sheet ${sheet.name}.`);
            continue;
        }

        for (const noteObj of notes) {
            const cellAddress = `${sheet.name}!${noteObj.Cell}`;
            console.log(`Processing note for cell: ${cellAddress}`);
            console.log(`Note content to be added: ${noteObj.Text}`);

            // Attempt to delete any existing comment using a try/catch block
            try {
                //console.log(`Attempting to delete existing comment at ${cellAddress}`);
                context.workbook.comments.getItemByCell(cellAddress).delete();
                await context.sync();
                //console.log(`Deleted existing comment at ${cellAddress}`);
            } catch (error) {
                // Handle the case where the comment does not exist
                if (error.code === "ItemNotFound") {
                    console.log(`No existing comment found at ${cellAddress}. Proceeding to add a new comment.`);
                } else {
                    // Re-throw the error if it's something else
                    console.error(`Error deleting comment at ${cellAddress}:`, error);
                    throw error;
                }
            }
            // Add the new comment using context
            console.log(`Adding new comment at ${cellAddress}`);
            context.workbook.comments.add(cellAddress, noteObj.Text);
            await context.sync();
            console.log(`Successfully added comment at ${cellAddress}`);
        }
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
                // Update the "RefersTo" formula of the existing named range
                existingName.formula = refersTo;
                console.log(`Named range "${name}" updated with new RefersTo value.`);
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
                    const numberFormats = Array(numRows).fill(Array(numColumns).fill(cell.NumberFormat));
                    range.numberFormat = numberFormats;
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

                // Load existing conditional formats with all necessary properties
                range.load("conditionalFormats/items/custom/rule/formula");
                await context.sync();

                // Delete existing conditional formats with the same formula
                const formatsToDelete = range.conditionalFormats.items.filter(
                    format => format.custom && format.custom.rule.formula === cf.Formula
                );
                formatsToDelete.forEach(format => format.delete());

                // Add the new conditional format
                let conditionalFormat = range.conditionalFormats.add(Excel.ConditionalFormatType.custom);
                conditionalFormat.custom.rule.formula = cf.Formula;

                if (cf.Interior) {
                    const interior = conditionalFormat.custom.format.fill;
                    if (cf.Interior.Color !== undefined) {
                        interior.color = cf.Interior.Color;
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

async function importListObjects(context, excelSheet, listObjects) {
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

                // Set column widths if provided
                for (let i = 0; i < listObject.Columns.length; i++) {
                    const column = listObject.Columns[i];
                    const tableColumn = newTable.columns.getItemAt(i);

                    if (column.Width) {
                        tableColumn.getRange().format.columnWidth = column.Width * 5;
                    }
                }

                // Now, add the rows to the table
                if (listObject.Rows && listObject.Rows.length > 0) {
                    console.log(`Adding ${listObject.Rows.length} rows to table ${newTable.name}`);

                    // Add the rows with values first
                    newTable.rows.add(null, listObject.Rows);
                    await context.sync();

                    // Handle formulas in the rows
                    const dataBodyRange = newTable.getDataBodyRange().load("values, formulas, rowCount, columnCount");
                    await context.sync();

                    for (let i = 0; i < dataBodyRange.rowCount; i++) {
                        for (let j = 0; j < dataBodyRange.columnCount; j++) {
                            const cellValue = dataBodyRange.values[i][j];
                            if (typeof cellValue === "string" && cellValue.startsWith("=")) {
                                dataBodyRange.getCell(i, j).formulas = [[cellValue]];
                            }
                        }
                    }

                    await context.sync();
                } else {
                    console.log(`No rows to add to table ${newTable.name}`);
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
            "StandardDeviationP": Excel.ShowAsCalculation.percentDifferenceFrom,
            "RankAscending": Excel.ShowAsCalculation.rankAscending,
            "RankDescending": Excel.ShowAsCalculation.rankDescending,
            "Index": Excel.ShowAsCalculation.index,
        };   

        const response = await fetch(`${window.appConfig.frontEndUrl}/assets/template.json`);
        if (!response.ok) {
            throw new Error('Failed to fetch JSON template');
        }
        const template = await response.json();

        await workbook.worksheets.load('items').context.sync();
        
        for (const sheet of template.Sheets) {
            console.log(`Processing Pivot tables in sheet: ${sheet.Name}`);

            // Ensure the sheet exists
            const destSheet = workbook.worksheets.getItemOrNullObject(sheet.Name);
            await destSheet.load('name').context.sync();
            if (destSheet.isNullObject) {
                console.error(`Sheet ${sheet.Name} does not exist.`);
                continue;
            }

            for (const pivotTable of sheet.PivotTables) {
                const existingPivotTable = destSheet.pivotTables.getItemOrNullObject(pivotTable.Name);
                await context.sync();

                if (existingPivotTable.isNullObject) {
                    // Get the destination range on the destination sheet
                    const destinationRange = destSheet.getRange(pivotTable.StartingCell);

                    console.log(`Creating PivotTable '${pivotTable.Name}' from source range '${pivotTable.SourceData}' on sheet '${destSheet.name}' at '${pivotTable.StartingCell}'`);

                    const newPivotTable = destSheet.pivotTables.add(pivotTable.Name, pivotTable.SourceData, destinationRange);
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
                    console.log(`Created pivot table: ${pivotTable.Name}`);
                } else {
                    console.log(`Pivot table ${pivotTable.Name} already exists, skipping.`);
                }
            }
        }

        console.log('All pivot tables processed successfully.');
    } catch (error) {
        console.error('Error recreating pivot tables:', error);
        createErrorCard('PivotTable', 'PIVOT_TABLE_ERROR', error.message);
        showToast('Failed to recreate pivot tables. Please try again.', 'error');
    }
}

function createCompositeKey(plaidAccountId, transactionId) {
    return `${plaidAccountId}_${transactionId}`;
}

function insertTransactionData(context, workbook, data, credentialsWithErrors) {
    const accountsData = [];
    const transactionsData = [];

    if (data.banks) {
        data.banks.forEach(bank => {
            if (credentialsWithErrors.has(bank.credential_id)) {
                console.log(`Skipping accounts for credential ID ${bank.credential_id} due to errors.`);
                return;
            }

            bank.accounts.forEach(account => {
                const concatenatedName = `${account.name} (${account.mask})`;

                const accountRow = [
                    bank.institution_name,
                    bank.credential_id,
                    bank.next_cursor,
                    account.type === 'credit' || account.type === 'loan' ? -account.balance : account.balance,
                    account.mask,
                    concatenatedName,
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
        const existingAccounts = accountsRange.values.reduce((map, row, index) => {
            map[row[6]] = { row, index }; // plaid_account_id is at index 6
            return map;
        }, {});

        const existingTransactions = transactionsRange.values.reduce((map, row, index) => {
            const plaidAccountId = row[0]; 
            const transactionId = row[10];
            if (plaidAccountId && transactionId) {
                const compositeKey = createCompositeKey(plaidAccountId, transactionId);
                map[compositeKey] = { row, index };
            } else {
                console.warn(`Skipping transaction at row ${index} due to missing plaidAccountId or transactionId.`);
            }
            return map;
        }, {});

        const newAccountsData = [];
        const newTransactionsData = [];
        const rowsToDeleteAccounts = [];

        // Process Accounts
        accountsData.forEach(accountRow => {
            const plaidAccountId = accountRow[6];
            if (existingAccounts[plaidAccountId]) {
                // Only mark for deletion if the account does not have errors
                if (!credentialsWithErrors.has(existingAccounts[plaidAccountId].row[1])) {
                    //console.log(`Marking account with ID ${plaidAccountId} for deletion.`);
                    rowsToDeleteAccounts.push(existingAccounts[plaidAccountId].index);
                }
            }
            newAccountsData.push(accountRow);
        });

        // Delete the account rows that are no longer needed
        if (rowsToDeleteAccounts.length > 0) {
            // Sort indices in descending order to prevent shifting
            rowsToDeleteAccounts.sort((a, b) => b - a);
            rowsToDeleteAccounts.forEach(rowIndex => {
                //console.log(`Deleting account row at index ${rowIndex}.`);
                accountsTable.rows.getItemAt(rowIndex).delete();
            });
        }

        // Insert new accounts data
        if (newAccountsData.length > 0) {
            //console.log(`Adding ${newAccountsData.length} new accounts.`);
            accountsTable.rows.add(null, newAccountsData);
        }

        // Process Transactions: Collect rows to delete
        const rowsToDeleteTransactions = [];
        transactionsData.forEach(transactionRow => {
            const plaidAccountId = transactionRow[0];
            const transactionId = transactionRow[10];
            
            if (!plaidAccountId || !transactionId) {
                //console.warn(`Skipping transaction due to missing plaidAccountId or transactionId:`, transactionRow);
                return; // Skip this transaction as it lacks necessary identifiers
            }
            
            const compositeKey = createCompositeKey(plaidAccountId.trim(), transactionId.trim());
            
            if (existingTransactions[compositeKey]) {
                //console.log(`Marking existing transaction with composite key: ${compositeKey} for deletion.`);
                rowsToDeleteTransactions.push(existingTransactions[compositeKey].index);
            }
            
            //console.log(`Adding new transaction with composite key: ${compositeKey}`);
            newTransactionsData.push(transactionRow);
        });

        // Delete the transaction rows that are no longer needed
        if (rowsToDeleteTransactions.length > 0) {
            // Sort indices in descending order to prevent shifting
            rowsToDeleteTransactions.sort((a, b) => b - a);
            rowsToDeleteTransactions.forEach(rowIndex => {
                // Fetch transaction details for logging before deletion
                const row = transactionsRange.values[rowIndex];
                const plaidAccountId = row[0];
                const transactionId = row[10];
                //console.log(`Deleting existing transaction:
    //- Institution (plaid_account_id): ${plaidAccountId}
    //- Transaction ID: ${transactionId}
    //- Reason: Transaction updated by institution.`);
                
                transactionsTable.rows.getItemAt(rowIndex).delete();
            });
        }

        // After deletions, sync to ensure rows are deleted before insertions
        return context.sync().then(() => {
            if (newTransactionsData.length > 0) {
                console.log(`Adding ${newTransactionsData.length} new transactions.`);
                const transactionColumns = transactionsRange.values[0]; // Assuming headers are loaded
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
        console.log('Starting to apply formulas to tables...');

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
                        const templateFormula = templateColumn.Formula;

                        if (templateFormula) {
                            const column = columns.items[i];
                            const columnRange = column.getDataBodyRange();
                            await columnRange.load('formulas, rowCount').context.sync();

                            // Check if there are any cells with a different formula
                            const needsUpdate = columnRange.formulas.some((rowFormula) => 
                                rowFormula.some((cellFormula) => cellFormula !== templateFormula)
                            );

                            if (needsUpdate) {
                                const rowCount = columnRange.rowCount;
                                const formulas = Array(rowCount).fill([templateFormula]);
                                console.log(`Applying formula to column: ${templateColumn.Header} with row count: ${rowCount}`);
                                columnRange.formulas = formulas;
                                await context.sync();
                            } else {
                                //console.log(`Skipping formula for column: ${templateColumn.Header} as it has not empty cells.`);
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

    cardsContainer.style.display = 'block';

    return card;
  }

  function createErrorCard(bankName, errorCode, errorMessage, credentialId) {
    console.log(`Creating error card for ${bankName} with code ${errorCode}`);
    const card = document.createElement('div');
    card.className = `error-card ${bankName.replace(/\s+/g, '-')}-card`;
  
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
  
    // Include the bank name and credential ID in the error message
    content.innerHTML = `
        <p><strong>Institution:</strong> ${bankName}</p>
        <p><strong>Credential ID:</strong> ${credentialId}</p>
        <p><strong>Error Code:</strong> ${errorCode}</p>
        <p>${errorMessage}</p>
    `;
  
    card.appendChild(closeButton);
    card.appendChild(content);
    cardsContainer.style.display = 'block'; // Ensure the container is visible
    cardsContainer.appendChild(card);
}

function createSuccessCard(institutionName, operation, transactionCount) {
    console.log(`Creating success card for ${institutionName} with ${transactionCount} transactions`);
    const successCard = createCard('success', institutionName, operation, transactionCount);
    document.getElementById('cardsContainer').appendChild(successCard);
}
