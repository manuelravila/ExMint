Attribute VB_Name = "Module1"
Sub IdentifySameFormulasToFile()
    Dim ws As Worksheet
    Dim cell As Range
    Dim firstFormula As String
    Dim currentFormula As String
    Dim formulaRange As Range
    Dim formulaRanges As Collection
    Dim result As String
    Dim filePath As String
    Dim fileNumber As Integer
    Dim lastRow As Long
    Dim currentRange As Range
    Dim col As Integer, row As Long
    Dim startRow As Long
    Dim tempResult As Variant ' Declare tempResult as Variant
    Dim lo As ListObject
    Dim pt As PivotTable
    Dim skipCell As Boolean
    
    Set ws = ThisWorkbook.Sheets("Dashboard")
    Set formulaRanges = New Collection
    result = ""
    filePath = "C:\Intel\FormulaRanges.txt"
    
    ' Loop through the first 100 columns
    For col = 1 To 100
        ' Find the last used row in the current column
        lastRow = ws.Cells(ws.Rows.Count, col).End(xlUp).row
        If lastRow = 1 And IsEmpty(ws.Cells(1, col)) Then
            ' Skip empty columns
            GoTo NextColumn
        End If

        Set currentRange = Nothing
        firstFormula = ""
        
        ' Loop through each row in the current column
        For row = 1 To lastRow
            Set cell = ws.Cells(row, col)
            
            skipCell = False
            
            ' Check if cell belongs to a ListObject
            For Each lo In ws.ListObjects
                If Not Intersect(cell, lo.Range) Is Nothing Then
                    skipCell = True
                    Exit For
                End If
            Next lo
            
            ' Check if cell belongs to a PivotTable
            If Not skipCell Then
                For Each pt In ws.PivotTables
                    If Not Intersect(cell, pt.TableRange2) Is Nothing Then
                        skipCell = True
                        Exit For
                    End If
                Next pt
            End If
            
            ' Process cell if it does not belong to ListObjects or PivotTables
            If Not skipCell And cell.HasFormula Then
                currentFormula = cell.FormulaR1C1
                
                If firstFormula = "" Then
                    ' Start a new range
                    Set currentRange = cell
                    firstFormula = currentFormula
                    startRow = row
                ElseIf currentFormula = firstFormula Then
                    ' Expand the current range
                    Set currentRange = Union(currentRange, cell)
                Else
                    ' Record the completed range
                    If Not currentRange Is Nothing And currentRange.Rows.Count > 1 Then
                        tempResult = ws.Cells(startRow, col).address & ":" & cell.Offset(-1, 0).address & "|" & ws.Cells(startRow, col).formula
                        formulaRanges.Add tempResult
                    End If
                    ' Start a new range
                    Set currentRange = cell
                    firstFormula = currentFormula
                    startRow = row
                End If
            ElseIf Not skipCell Then
                ' Record the completed range if formula ends
                If Not currentRange Is Nothing Then
                    If currentRange.Rows.Count > 1 Then
                        tempResult = ws.Cells(startRow, col).address & ":" & cell.Offset(-1, 0).address & "|" & ws.Cells(startRow, col).formula
                        formulaRanges.Add tempResult
                    End If
                    Set currentRange = Nothing
                    firstFormula = ""
                End If
            End If
        Next row
        
        ' Record the last range in the column
        If Not currentRange Is Nothing Then
            If currentRange.Rows.Count > 1 Then
                tempResult = ws.Cells(startRow, col).address & ":" & ws.Cells(lastRow, col).address & "|" & ws.Cells(startRow, col).formula
                formulaRanges.Add tempResult
            End If
        End If

NextColumn:
    Next col
    
    ' Loop through the collected formula ranges and build the result string
    For Each tempResult In formulaRanges
        result = result & tempResult & vbCrLf
    Next tempResult
    
    ' Write the result to a text file
    fileNumber = FreeFile
    Open filePath For Output As #fileNumber
    Print #fileNumber, result
    Close #fileNumber
    
    MsgBox "Formulas identified and saved to " & filePath, vbInformation, "Process Complete"
End Sub

