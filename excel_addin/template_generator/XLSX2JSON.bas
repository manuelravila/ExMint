Attribute VB_Name = "XLSX2JSON"
Option Explicit

' Main function to convert XLSX to JSON
Public Sub XLSX2JSON()
    Dim wb As Workbook
    Dim ws As Worksheet
    Dim jsonString As String
    Dim fso As Object
    Dim jsonFile As Object
    Dim filePath As String
    Dim originalPath As String
    
    Set wb = ThisWorkbook
    originalPath = wb.Path
    
    ' Start building JSON string
    jsonString = "{"
    jsonString = jsonString & vbCrLf & "  ""Sheets"": [" & vbCrLf
    
    ' Loop through all worksheets
    For Each ws In wb.Worksheets
        jsonString = jsonString & ConvertWorksheetToJSON(ws)
        If Not ws Is wb.Worksheets(wb.Worksheets.Count) Then
            jsonString = jsonString & "," & vbCrLf
        End If
    Next ws
    
    jsonString = jsonString & vbCrLf & "  ]," & vbCrLf
    
    ' Add custom named ranges
    jsonString = jsonString & "  ""CustomNamedRanges"": " & ConvertNamedRangesToJSON(wb) & vbCrLf
    
    ' Close the main JSON object
    jsonString = jsonString & "}"
    
    ' Determine the JSON file path
    filePath = GetJsonFilePath(wb)
    
    ' Save JSON to file
    Set fso = CreateObject("Scripting.FileSystemObject")
    On Error Resume Next
    Set jsonFile = fso.CreateTextFile(filePath, True)
    If Err.Number <> 0 Then
        MsgBox "Error creating file: " & Err.Description & vbNewLine & _
               "Path: " & filePath, vbExclamation
        Exit Sub
    End If
    On Error GoTo 0
    
    jsonFile.Write jsonString
    jsonFile.Close
    
    MsgBox "JSON file saved successfully at: " & filePath, vbInformation
End Sub

' Function to get the JSON file path
Private Function GetJsonFilePath(wb As Workbook) As String
    Dim savePath As String
    Dim fileName As String
    Dim invalidChars As String
    Dim i As Integer
    Dim isOneDrive As Boolean
    Dim relativePath As String
    
    ' Check if the workbook is on OneDrive
    isOneDrive = InStr(1, wb.Path, "https://") > 0 Or InStr(1, wb.Path, "http://") > 0
    
    If isOneDrive Then
        ' Extract the relative path from the OneDrive URL
        relativePath = Replace(wb.Path, "https://d.docs.live.net/", "")
        relativePath = Mid(relativePath, InStr(relativePath, "/") + 1)
        
        ' Construct a path to the user's local OneDrive folder with relative path
        savePath = "C:\Users\" & Environ$("Username") & "\OneDrive\" & relativePath
        
        ' If OneDrive folder doesn't exist, fall back to Documents folder
        If Dir(savePath, vbDirectory) = "" Then
            savePath = Environ$("USERPROFILE") & "\Documents\" & relativePath
        End If
    ElseIf wb.Path <> "" Then
        ' Use the workbook's current path if it's not on OneDrive and has been saved
        savePath = wb.Path
    Else
        ' Fallback to Desktop if everything else fails
        savePath = Environ$("USERPROFILE") & "\Desktop"
    End If
    
    ' Create the directory if it doesn't exist
    If Dir(savePath, vbDirectory) = "" Then
        MkDir savePath
    End If
    
    ' Get the file name without extension
    fileName = Left(wb.Name, InStrRev(wb.Name, ".") - 1)
    
    ' Remove invalid characters from the file name
    invalidChars = "\/:|<>*?" & Chr(34)
    For i = 1 To Len(invalidChars)
        fileName = Replace(fileName, Mid(invalidChars, i, 1), "_")
    Next i
    
    ' Ensure the file name is not too long (max 255 characters for the entire path)
    If Len(savePath & "\" & fileName & ".json") > 255 Then
        fileName = Left(fileName, 250 - Len(savePath) - 6) ' 6 for "\.json"
    End If
    
    ' Combine save path, file name, and .json extension
    GetJsonFilePath = savePath & "\" & fileName & ".json"
End Function

' Function to convert a worksheet to JSON
Private Function ConvertWorksheetToJSON(ws As Worksheet) As String
    Dim jsonWs As String
    Dim lo As ListObject
    Dim pt As PivotTable
    Dim group As Variant
    Dim formulaGroups As Collection
    Dim i As Long
    Dim tempStr As String

    jsonWs = "    {" & vbCrLf
    jsonWs = jsonWs & "      ""Name"": """ & ws.Name & """," & vbCrLf

    ' Convert ListObject tables
    tempStr = ""
    jsonWs = jsonWs & "      ""ListObjects"": [" & vbCrLf
    For i = 1 To ws.listObjects.Count
        Set lo = ws.listObjects(i)
        tempStr = tempStr & ConvertListObjectToJSON(lo)
        If i < ws.listObjects.Count Then
            tempStr = tempStr & "," & vbCrLf
        End If
    Next i
    jsonWs = jsonWs & tempStr & vbCrLf & "      ]," & vbCrLf

    ' Convert PivotTables
    tempStr = ""
    jsonWs = jsonWs & "      ""PivotTables"": [" & vbCrLf
    For i = 1 To ws.pivotTables.Count
        Set pt = ws.pivotTables(i)
        tempStr = tempStr & ConvertPivotTableToJSON(pt)
        If i < ws.pivotTables.Count Then
            tempStr = tempStr & "," & vbCrLf
        End If
    Next i
    jsonWs = jsonWs & tempStr & vbCrLf & "      ]," & vbCrLf

    ' Convert other cells
    tempStr = ""
    jsonWs = jsonWs & "      ""OtherCells"": [" & vbCrLf
    Set formulaGroups = GroupCellsByFormula(ws)
    For i = 1 To formulaGroups.Count
        tempStr = tempStr & ConvertCellGroupToJSON(formulaGroups(i))
        If i < formulaGroups.Count Then
            tempStr = tempStr & "," & vbCrLf
        End If
    Next i
    jsonWs = jsonWs & tempStr & vbCrLf & "      ]," & vbCrLf

    ' Convert individual cells with values
    tempStr = ""
    jsonWs = jsonWs & "      ""Cells"": [" & vbCrLf
    tempStr = ConvertCellsToJSON(ws, formulaGroups)
    If Right(tempStr, 2) = "," & vbCrLf Then tempStr = Left(tempStr, Len(tempStr) - 2) ' Remove trailing comma
    jsonWs = jsonWs & tempStr & vbCrLf & "      ]," & vbCrLf

    ' Convert data validations
    tempStr = ""
    jsonWs = jsonWs & "      ""DataValidations"": [" & vbCrLf
    tempStr = ConvertDataValidationsToJSON(ws)
    If Right(tempStr, 2) = "," & vbCrLf Then tempStr = Left(tempStr, Len(tempStr) - 2) ' Remove trailing comma
    jsonWs = jsonWs & tempStr & vbCrLf & "      ]," & vbCrLf

    ' Convert conditional formatting
    tempStr = ""
    jsonWs = jsonWs & "      ""ConditionalFormatting"": [" & vbCrLf
    tempStr = ConvertConditionalFormattingToJSON(ws)
    If Right(tempStr, 2) = "," & vbCrLf Then tempStr = Left(tempStr, Len(tempStr) - 2) ' Remove trailing comma
    jsonWs = jsonWs & tempStr & vbCrLf & "      ]" & vbCrLf

    jsonWs = jsonWs & "    }"

    ConvertWorksheetToJSON = jsonWs
End Function


' Function to convert a ListObject to JSON
Private Function ConvertListObjectToJSON(lo As ListObject) As String
    Dim jsonLo As String
    Dim col As ListColumn
    Dim row As ListRow
    Dim cell As Range
    Dim rngDataBody As Range
    Dim rngLstObj As Range
    Dim c As Long
    Dim r As Long
    Dim tempRowsAdded As Boolean
    Dim tempRowCount As Long
    Dim i As Long
    Dim tempStr As String
    Dim rowValues As String
    Dim firstRowHasValues As Boolean

    jsonLo = "        {" & vbCrLf
    jsonLo = jsonLo & "          ""Name"": """ & Trim(lo.Name) & """," & vbCrLf
    jsonLo = jsonLo & "          ""StartingCell"": """ & lo.Range.Cells(1, 1).address & """," & vbCrLf
    jsonLo = jsonLo & "          ""ColorStyle"": """ & lo.TableStyle & """," & vbCrLf

    ' Check if the ListObject has a DataBodyRange
    On Error Resume Next
    Set rngDataBody = lo.DataBodyRange
    On Error GoTo 0

    ' Check if the first row has any values
    firstRowHasValues = False
    If Not rngDataBody Is Nothing Then
        For Each cell In rngDataBody.Rows(1).Cells
            If Not IsEmpty(cell.value) Then
                firstRowHasValues = True
                Exit For
            End If
        Next cell
    End If

    ' Convert columns
    tempStr = ""
    jsonLo = jsonLo & "          ""Columns"": [" & vbCrLf

    If rngDataBody Is Nothing Then
        ' No data because all rows deleted
        With lo.Range
            ' Resize the ListObject range to provide 2 temporary rows in the DataBodyRange
            Set rngLstObj = .Resize(.Rows.Count + 2, .Columns.Count)
        End With

        lo.Resize rngLstObj ' Resize the ListObject with the added 2 temporary rows in ListObject range
        tempRowsAdded = True
        tempRowCount = 2
    Else
        tempRowCount = 0
    End If

    For i = 1 To lo.ListColumns.Count
        Set col = lo.ListColumns(i)
        tempStr = tempStr & "            {" & vbCrLf
        tempStr = tempStr & "              ""Header"": """ & Trim(col.Name) & """," & vbCrLf
        tempStr = tempStr & "              ""Width"": " & col.Range.ColumnWidth & "," & vbCrLf

        ' Only include "Formula" key if the first row has no values
        If firstRowHasValues Then
            tempStr = tempStr & "              ""Formula"": """"" & vbCrLf
        ElseIf Not col.DataBodyRange Is Nothing Then
            If col.DataBodyRange.Rows.Count > 0 Then
                tempStr = tempStr & "              ""Formula"": """ & EscapeJsonString(col.DataBodyRange.Cells(1, 1).formula) & """" & vbCrLf
            Else
                tempStr = tempStr & "              ""Formula"": """"" & vbCrLf ' Empty formula if no rows
            End If
        Else
            tempStr = tempStr & "              ""Formula"": """"" & vbCrLf ' Empty formula if DataBodyRange is Nothing
        End If

        tempStr = tempStr & "            }"
        If i < lo.ListColumns.Count Then
            tempStr = tempStr & "," & vbCrLf
        End If
    Next i
    jsonLo = jsonLo & tempStr & vbCrLf & "          ]," & vbCrLf

    ' Convert rows
    tempStr = ""
    jsonLo = jsonLo & "          ""Rows"": [" & vbCrLf

    If lo.ListColumns.Count > 0 And Not rngDataBody Is Nothing Then
        For r = 1 To lo.ListRows.Count - tempRowCount
            rowValues = "            ["
            For c = 1 To lo.ListColumns.Count
                Set row = lo.ListRows(r)
                If row.Range.Cells(1, c).HasFormula Then
                    rowValues = rowValues & """" & EscapeJsonString(row.Range.Cells(1, c).formula) & """"
                Else
                    rowValues = rowValues & """" & EscapeJsonString(CStr(row.Range.Cells(1, c).value)) & """"
                End If
                If c < lo.ListColumns.Count Then
                    rowValues = rowValues & ", "
                End If
            Next c
            rowValues = rowValues & "]"
            tempStr = tempStr & rowValues
            If r < lo.ListRows.Count - tempRowCount Then
                tempStr = tempStr & "," & vbCrLf
            End If
        Next r
    End If

    jsonLo = jsonLo & tempStr & vbCrLf & "          ]" & vbCrLf

    jsonLo = jsonLo & "        }"

    ' If temporary rows were added, delete them
    If tempRowsAdded Then
        With lo
            ' Delete the added temporary rows from DataBodyRange (Works backwards)
            For r = .ListRows.Count To 1 Step -1
                .ListRows(r).Delete
            Next r
        End With
    End If

    ConvertListObjectToJSON = jsonLo
End Function

Private Function ConvertPivotTableToJSON(pt As PivotTable) As String
    Dim jsonPt As String
    Dim pf As PivotField
    Dim i As Long
    Dim orderedRowFields() As PivotField
    Dim orderedColumnFields() As PivotField
    Dim orderedValueFields() As PivotField

    ' Initialize JSON string
    jsonPt = "        {" & vbCrLf
    jsonPt = jsonPt & "          ""Name"": """ & Trim(pt.Name) & """," & vbCrLf
    jsonPt = jsonPt & "          ""StartingCell"": """ & pt.TableRange1.Cells(1, 1).address & """," & vbCrLf
    jsonPt = jsonPt & "          ""ColorStyle"": """ & pt.TableStyle & """," & vbCrLf
    jsonPt = jsonPt & "          ""SourceData"": """ & pt.SourceData & """," & vbCrLf

    ' Convert row fields
    If pt.RowFields.Count > 0 Then
        ReDim orderedRowFields(1 To pt.RowFields.Count)
        For i = 1 To pt.RowFields.Count
            Set orderedRowFields(pt.RowFields(i).Position) = pt.RowFields(i)
        Next i
    End If
    jsonPt = jsonPt & "          ""RowFields"": [" & vbCrLf
    If pt.RowFields.Count > 0 Then
        For i = 1 To UBound(orderedRowFields)
            Set pf = orderedRowFields(i)
            jsonPt = jsonPt & "            {" & vbCrLf
            jsonPt = jsonPt & "              ""Name"": """ & Trim(pf.Name) & """," & vbCrLf
            jsonPt = jsonPt & "              ""CustomName"": """ & Trim(pf.Caption) & """," & vbCrLf
            jsonPt = jsonPt & "              ""Subtotals"": " & BooleanToLowercase(pf.Subtotals(1)) & "," & vbCrLf
            jsonPt = jsonPt & "              ""LayoutForm"": """ & pf.LayoutForm & """" & vbCrLf
            jsonPt = jsonPt & "            }"
            If i < UBound(orderedRowFields) Then
                jsonPt = jsonPt & "," & vbCrLf
            End If
        Next i
    End If
    jsonPt = jsonPt & vbCrLf & "          ]," & vbCrLf

    ' Convert column fields
    If pt.ColumnFields.Count > 0 Then
        ReDim orderedColumnFields(1 To pt.ColumnFields.Count)
        For i = 1 To pt.ColumnFields.Count
            Set orderedColumnFields(pt.ColumnFields(i).Position) = pt.ColumnFields(i)
        Next i
    End If
    jsonPt = jsonPt & "          ""ColumnFields"": [" & vbCrLf
    If pt.ColumnFields.Count > 0 Then
        For i = 1 To UBound(orderedColumnFields)
            Set pf = orderedColumnFields(i)
            If pf.Name <> "Values" Then
                jsonPt = jsonPt & "            {" & vbCrLf
                jsonPt = jsonPt & "              ""Name"": """ & Trim(pf.Name) & """," & vbCrLf
                jsonPt = jsonPt & "              ""CustomName"": """ & Trim(pf.Caption) & """" & vbCrLf
                jsonPt = jsonPt & "            }"
                If i < UBound(orderedColumnFields) Then
                    jsonPt = jsonPt & "," & vbCrLf
                End If
            End If
        Next i
    End If
    jsonPt = jsonPt & vbCrLf & "          ]," & vbCrLf

    ' Convert value fields
    If pt.DataFields.Count > 0 Then
        ReDim orderedValueFields(1 To pt.DataFields.Count)
        For i = 1 To pt.DataFields.Count
            Set orderedValueFields(pt.DataFields(i).Position) = pt.DataFields(i)
        Next i
    End If
    jsonPt = jsonPt & "          ""ValueFields"": [" & vbCrLf
    If pt.DataFields.Count > 0 Then
        For i = 1 To UBound(orderedValueFields)
            Set pf = orderedValueFields(i)
            jsonPt = jsonPt & "            {" & vbCrLf
            jsonPt = jsonPt & "              ""Name"": """ & Trim(pf.SourceName) & """," & vbCrLf
            jsonPt = jsonPt & "              ""CustomName"": """ & Trim(pf.Caption) & """," & vbCrLf
            jsonPt = jsonPt & "              ""SummarizedBy"": """ & GetAggregationFunctionName(pf.Function) & """," & vbCrLf
            jsonPt = jsonPt & "              ""ShowValuesAs"": """ & GetShowAsCalculationName(pf.Calculation) & """," & vbCrLf
            jsonPt = jsonPt & "              ""NumberFormat"": """ & pf.numberFormat & """" & vbCrLf
            jsonPt = jsonPt & "            }"
            If i < UBound(orderedValueFields) Then
                jsonPt = jsonPt & "," & vbCrLf
            End If
        Next i
    End If
    jsonPt = jsonPt & vbCrLf & "          ]" & vbCrLf

    jsonPt = jsonPt & "        }"

    ConvertPivotTableToJSON = jsonPt
End Function


' Helper function to get aggregation function name from its code
Private Function GetAggregationFunctionName(code As Long) As String
    Select Case code
        Case -4157: GetAggregationFunctionName = "Sum"
        Case -4112: GetAggregationFunctionName = "Count"
        Case -4105: GetAggregationFunctionName = "Average"
        Case -4136: GetAggregationFunctionName = "Max"
        Case -4139: GetAggregationFunctionName = "Min"
        Case -4149: GetAggregationFunctionName = "Product"
        Case -4144: GetAggregationFunctionName = "CountNumbers"
        Case -4155: GetAggregationFunctionName = "StandardDeviation"
        Case -4130: GetAggregationFunctionName = "StandardDeviationP"
        Case -4161: GetAggregationFunctionName = "Variance"
        Case -4162: GetAggregationFunctionName = "VarianceP"
        Case Else: GetAggregationFunctionName = "Automatic"
    End Select
End Function

' Helper function to get show as calculation name from its code
Private Function GetShowAsCalculationName(code As Long) As String
    Select Case code
        Case -4143: GetShowAsCalculationName = "None"
        Case 2: GetShowAsCalculationName = "PercentOfGrandTotal"
        Case 3: GetShowAsCalculationName = "PercentOfRowTotal"
        Case 4: GetShowAsCalculationName = "PercentOfColumnTotal"
        Case 5: GetShowAsCalculationName = "PercentOfParentRowTotal"
        Case 6: GetShowAsCalculationName = "PercentOfParentColumnTotal"
        Case 7: GetShowAsCalculationName = "PercentOfParentTotal"
        Case 8: GetShowAsCalculationName = "PercentOf"
        Case 9: GetShowAsCalculationName = "RunningTotal"
        Case 10: GetShowAsCalculationName = "PercentRunningTotal"
        Case 11: GetShowAsCalculationName = "DifferenceFrom"
        Case 12: GetShowAsCalculationName = "PercentDifferenceFrom"
        Case 13: GetShowAsCalculationName = "RankAscending"
        Case 14: GetShowAsCalculationName = "RankDescending"
        Case 15: GetShowAsCalculationName = "Index"
        Case Else: GetShowAsCalculationName = "Unknown"
    End Select
End Function

' Function to convert named ranges to JSON
Private Function ConvertNamedRangesToJSON(wb As Workbook) As String
    Dim jsonNr As String
    Dim nm As Name

    jsonNr = "[" & vbCrLf
    For Each nm In wb.Names
        ' Exclude hidden names and internal names starting with "_xlfn" or "_xlpm"
        If nm.Visible Then
            jsonNr = jsonNr & "    {" & vbCrLf
            jsonNr = jsonNr & "      ""Name"": """ & nm.Name & """," & vbCrLf
            jsonNr = jsonNr & "      ""RefersTo"": """ & Replace(Replace(nm.RefersTo, vbCr, ""), vbLf, "") & """" & vbCrLf
            jsonNr = jsonNr & "    },"
        End If
    Next nm
    ' Remove the trailing comma and add closing bracket
    If Right(jsonNr, 1) = "," Then jsonNr = Left(jsonNr, Len(jsonNr) - 1)
    jsonNr = jsonNr & vbCrLf & "  ]"

    ConvertNamedRangesToJSON = jsonNr
End Function


' Function to convert a cell group to JSON with range handling
Private Function ConvertCellGroupToJSON(group As Variant) As String
    Dim jsonGroup As String
    Dim splitKey() As String
    Dim formula As String
    Dim rangeStart As Long
    Dim rangeEnd As Long
    Dim colRef As String
    Dim cell As Range

    splitKey = Split(group(0), "|")
    formula = group(1)
    rangeStart = CLng(Split(splitKey(1), ":")(0))
    rangeEnd = CLng(Split(splitKey(1), ":")(1))

    ' Extract the column reference
    colRef = splitKey(0)

    ' Assuming the first cell in the range is representative of the formatting
    Set cell = group(2)

    ' Get cell formatting
    Dim fillColorHex As String
    Dim numberFormat As String
    Dim fontColorHex As String
    Dim fontSizeStr As String
    Dim fontBoldStr As String
    Dim fontItalicStr As String

    If IsNull(cell.Interior.Color) Then
        fillColorHex = "null"
    Else
        fillColorHex = """" & ColorToHex(cell.Interior.Color) & """"
    End If

    If IsNull(cell.Font.Color) Then
        fontColorHex = "null"
    Else
        fontColorHex = """" & ColorToHex(cell.Font.Color) & """"
    End If

    If IsNull(cell.Font.Size) Then
        fontSizeStr = "null"
    Else
        fontSizeStr = cell.Font.Size
    End If

    If IsNull(cell.Font.Bold) Then
        fontBoldStr = "null"
    Else
        fontBoldStr = LCase(CStr(cell.Font.Bold))
    End If

    If IsNull(cell.Font.Italic) Then
        fontItalicStr = "null"
    Else
        fontItalicStr = LCase(CStr(cell.Font.Italic))
    End If

    numberFormat = cell.numberFormat

    jsonGroup = "        {" & vbCrLf
    jsonGroup = jsonGroup & "          ""Address"": """ & "$" & colRef & "$" & rangeStart & ":$" & colRef & "$" & rangeEnd & """," & vbCrLf
    jsonGroup = jsonGroup & "          ""Formula"": """ & EscapeJsonString(formula) & """," & vbCrLf
    jsonGroup = jsonGroup & "          ""FillColor"": " & fillColorHex & "," & vbCrLf
    jsonGroup = jsonGroup & "          ""NumberFormat"": """ & numberFormat & """," & vbCrLf
    jsonGroup = jsonGroup & "          ""Font"": {" & vbCrLf
    jsonGroup = jsonGroup & "              ""Size"": " & fontSizeStr & "," & vbCrLf
    jsonGroup = jsonGroup & "              ""Color"": " & fontColorHex & "," & vbCrLf
    jsonGroup = jsonGroup & "              ""Bold"": " & fontBoldStr & "," & vbCrLf
    jsonGroup = jsonGroup & "              ""Italic"": " & fontItalicStr & vbCrLf
    jsonGroup = jsonGroup & "          }" & vbCrLf
    jsonGroup = jsonGroup & "        }"

    ConvertCellGroupToJSON = jsonGroup
End Function

' Function to convert individual cells with values to JSON
Private Function ConvertCellsToJSON(ws As Worksheet, formulaGroups As Collection) As String
    Dim jsonCells As String
    Dim cell As Range
    Dim firstCell As Boolean
    Dim fontColorHex As String
    Dim fontSizeStr As String
    Dim fontBoldStr As String
    Dim fontItalicStr As String
    Dim fillColorHex As String
    Dim cellRange As Range
    Dim lo As ListObject
    Dim pt As PivotTable
    Dim skipCell As Boolean
    Dim group As Variant
    Dim groupAddress As String
    Dim colRef As String
    Dim rowRef As String

    jsonCells = ""
    firstCell = True

    For Each cell In ws.UsedRange
        skipCell = False

        ' Check if cell is part of a ListObject
        For Each lo In ws.listObjects
            If Not Intersect(cell, lo.Range) Is Nothing Then
                skipCell = True
                Exit For
            End If
        Next lo

        ' Check if cell is part of a PivotTable
        If Not skipCell Then
            For Each pt In ws.pivotTables
                If Not Intersect(cell, pt.TableRange2) Is Nothing Then
                    skipCell = True
                    Exit For
                End If
            Next pt
        End If

        ' Check if cell is part of a formula group
        If Not skipCell Then
            For Each group In formulaGroups
                On Error Resume Next
                colRef = Split(group(0), "|")(0)
                rowRef = Split(group(0), "|")(1)
                groupAddress = colRef & Left(rowRef, InStr(rowRef, ":") - 1) & ":" & colRef & Mid(rowRef, InStr(rowRef, ":") + 1)
                Set cellRange = ws.Range(groupAddress)
                On Error GoTo 0
                If Not cellRange Is Nothing And Not Intersect(cell, cellRange) Is Nothing Then
                    skipCell = True
                    Exit For
                End If
            Next group
        End If

        ' Process cell if it is not part of any of the above
        If Not skipCell And Not IsEmpty(cell.value) Then
            If Not firstCell Then
                jsonCells = jsonCells & "," & vbCrLf
            End If
            firstCell = False

            ' Get cell formatting
            If IsNull(cell.Interior.Color) Then
                fillColorHex = "null"
            Else
                fillColorHex = """" & ColorToHex(cell.Interior.Color) & """"
            End If

            If IsNull(cell.Font.Color) Then
                fontColorHex = "null"
            Else
                fontColorHex = """" & ColorToHex(cell.Font.Color) & """"
            End If

            If IsNull(cell.Font.Size) Then
                fontSizeStr = "null"
            Else
                fontSizeStr = cell.Font.Size
            End If

            If IsNull(cell.Font.Bold) Then
                fontBoldStr = "null"
            Else
                fontBoldStr = LCase(CStr(cell.Font.Bold))
            End If

            If IsNull(cell.Font.Italic) Then
                fontItalicStr = "null"
            Else
                fontItalicStr = LCase(CStr(cell.Font.Italic))
            End If

            jsonCells = jsonCells & "        {" & vbCrLf
            jsonCells = jsonCells & "          ""Address"": """ & cell.address & """," & vbCrLf
            jsonCells = jsonCells & "          ""Value"": """ & EscapeJsonString(CStr(cell.value)) & """," & vbCrLf
            jsonCells = jsonCells & "          ""FillColor"": " & fillColorHex & "," & vbCrLf
            jsonCells = jsonCells & "          ""NumberFormat"": """ & cell.numberFormat & """," & vbCrLf
            jsonCells = jsonCells & "          ""Font"": {" & vbCrLf
            jsonCells = jsonCells & "              ""Size"": " & fontSizeStr & "," & vbCrLf
            jsonCells = jsonCells & "              ""Color"": " & fontColorHex & "," & vbCrLf
            jsonCells = jsonCells & "              ""Bold"": " & fontBoldStr & "," & vbCrLf
            jsonCells = jsonCells & "              ""Italic"": " & fontItalicStr & vbCrLf
            jsonCells = jsonCells & "          }" & vbCrLf
            jsonCells = jsonCells & "        }"
        End If
    Next cell

    ConvertCellsToJSON = jsonCells
End Function


' Function to escape special characters in JSON strings and properly handle line breaks
Private Function EscapeJsonString(ByVal text As String) As String
    Dim i As Long
    Dim char As String
    Dim ascChar As Integer
    Dim result As String

    ' Remove line breaks and carriage returns
    text = Replace(text, vbCr, "")
    text = Replace(text, vbLf, "")

    For i = 1 To Len(text)
        char = Mid(text, i, 1)
        ascChar = Asc(char)

        Select Case ascChar
            Case 34 ' "
                result = result & "\"""
            Case 92 ' \
                result = result & "\\"
            Case 47 ' /
                result = result & "/"
            Case 8  ' vbBack
                result = result & "\b"
            Case 12 ' vbFormFeed
                result = result & "\f"
            Case 9  ' vbTab
                result = result & "\t"
            Case Else
                If ascChar < 32 Or ascChar > 127 Then
                    result = result & "\u" & Right("0000" & Hex(ascChar), 4)
                Else
                    result = result & char
                End If
        End Select
    Next i

    EscapeJsonString = result
End Function

' Function to group cells by formula with consideration of relative references
Private Function GroupCellsByFormula(ws As Worksheet) As Collection
    Dim cell As Range
    Dim dict As Object
    Dim key As String
    Dim formulaBase As String
    Dim groups As Collection
    Dim startRow As Long
    Dim endRow As Long
    Dim currentFormula As String
    Dim lastFormula As String
    Dim colRef As String
    Dim lo As ListObject
    Dim pt As PivotTable
    Dim skipCell As Boolean
    Dim lastRow As Long
    Dim tempResult As Variant
    Dim col As Integer, row As Long
    Dim currentRange As Range ' Declare currentRange as Range
    
    Set dict = CreateObject("Scripting.Dictionary")
    Set groups = New Collection
    
    ' Loop through the first 100 columns
    For col = 1 To 100
        ' Find the last used row in the current column
        lastRow = ws.Cells(ws.Rows.Count, col).End(xlUp).row
        If lastRow = 1 And IsEmpty(ws.Cells(1, col)) Then
            ' Skip empty columns
            GoTo NextColumn
        End If

        Set currentRange = Nothing
        lastFormula = ""
        colRef = ""
        
        ' Loop through each row in the current column
        For row = 1 To lastRow
            Set cell = ws.Cells(row, col)
            
            skipCell = False
            
            ' Check if cell belongs to a ListObject
            For Each lo In ws.listObjects
                If Not Intersect(cell, lo.Range) Is Nothing Then
                    skipCell = True
                    Exit For
                End If
            Next lo
            
            ' Check if cell belongs to a PivotTable
            If Not skipCell Then
                For Each pt In ws.pivotTables
                    If Not Intersect(cell, pt.TableRange2) Is Nothing Then
                        skipCell = True
                        Exit For
                    End If
                Next pt
            End If
            
            ' Process cell if it does not belong to ListObjects or PivotTables
            If Not skipCell And cell.HasFormula Then
                currentFormula = cell.FormulaR1C1
                
                If lastFormula = "" Then
                    ' Start a new range
                    startRow = cell.row
                    endRow = startRow
                    lastFormula = currentFormula
                    colRef = ExtractColumnReference(cell.address)
                    Set currentRange = cell ' Set the first cell for formatting
                ElseIf currentFormula = lastFormula And colRef = ExtractColumnReference(cell.address) Then
                    ' Extend the current range
                    endRow = cell.row
                Else
                    ' Add the previous range to the dictionary
                    If lastFormula <> "" Then
                        key = colRef & "|" & startRow & ":" & endRow
                        dict.Add key, Array(lastFormula, currentRange) ' Pass the first cell
                    End If
                    ' Start a new range
                    startRow = cell.row
                    endRow = startRow
                    lastFormula = currentFormula
                    colRef = ExtractColumnReference(cell.address)
                    Set currentRange = cell ' Set the first cell for formatting
                End If
            ElseIf Not skipCell Then
                ' Record the completed range if formula ends
                If lastFormula <> "" Then
                    key = colRef & "|" & startRow & ":" & endRow
                    dict.Add key, Array(lastFormula, currentRange) ' Pass the first cell
                    lastFormula = ""
                End If
            End If
        Next row
        
        ' Add the last range to the dictionary
        If lastFormula <> "" Then
            key = colRef & "|" & startRow & ":" & endRow
            dict.Add key, Array(lastFormula, currentRange) ' Pass the first cell
        End If
        
NextColumn:
    Next col
    
    ' Convert dictionary to collection
    Dim dictKey As Variant
    For Each dictKey In dict.Keys
        groups.Add Array(dictKey, dict(dictKey)(0), dict(dictKey)(1))
    Next dictKey
    
    Set GroupCellsByFormula = groups
End Function

' Function to extract the column reference from a cell address
Private Function ExtractColumnReference(address As String) As String
    Dim colRef As String
    Dim regex As Object
    Set regex = CreateObject("VBScript.RegExp")
    
    ' Pattern to match a column reference (e.g., H)
    regex.Pattern = "[A-Z]+"
    regex.Global = False
    
    ' Extract the first match
    If regex.Test(address) Then
        colRef = regex.Execute(address)(0).value
    Else
        colRef = "A" ' Default value if no match found
    End If
    
    ExtractColumnReference = colRef
End Function

' Function to convert conditional formatting to JSON
Private Function ConvertConditionalFormattingToJSON(ws As Worksheet) As String
    Dim jsonCf As String
    Dim cf As formatCondition
    Dim rg As Range
    Dim colFormatConditions As Collection
    Dim colRange As Range
    Dim i As Long
    Dim tempStr As String
    Dim fontColorHex As String
    Dim fontSizeStr As String
    Dim fontBoldStr As String
    Dim fontItalicStr As String

    Set colFormatConditions = New Collection
    jsonCf = ""

    For i = 1 To ws.Cells.FormatConditions.Count
        Set cf = ws.Cells.FormatConditions(i)
        Set colRange = cf.AppliesTo
        tempStr = tempStr & "        {" & vbCrLf
        tempStr = tempStr & "          ""AppliesTo"": """ & colRange.address & """," & vbCrLf
        tempStr = tempStr & "          ""Type"": """ & cf.Type & """," & vbCrLf
        tempStr = tempStr & "          ""Formula"": """ & EscapeJsonString(cf.formula1) & """," & vbCrLf

        On Error Resume Next
        Dim operatorExists As Boolean
        operatorExists = Not IsEmpty(cf.Operator)
        On Error GoTo 0

        If operatorExists Then
            tempStr = tempStr & "          ""Operator"": """ & cf.Operator & """," & vbCrLf
        End If

        tempStr = tempStr & "          ""Interior"": {" & vbCrLf
        tempStr = tempStr & "              ""Color"": """ & ColorToHex(cf.Interior.Color) & """," & vbCrLf
        tempStr = tempStr & "              ""Pattern"": """ & cf.Interior.Pattern & """" & vbCrLf
        tempStr = tempStr & "          }," & vbCrLf

        ' Check if Font.Color is Null and handle accordingly
        If IsNull(cf.Font.Color) Then
            fontColorHex = "null"
        Else
            fontColorHex = """" & ColorToHex(cf.Font.Color) & """"
        End If

        ' Check if Font.Size is Null and handle accordingly
        If IsNull(cf.Font.Size) Then
            fontSizeStr = "null"
        Else
            fontSizeStr = cf.Font.Size
        End If

        ' Check if Font.Bold is Null and handle accordingly
        If IsNull(cf.Font.Bold) Then
            fontBoldStr = "null"
        Else
            fontBoldStr = LCase(CStr(cf.Font.Bold))
        End If

        ' Check if Font.Italic is Null and handle accordingly
        If IsNull(cf.Font.Italic) Then
            fontItalicStr = "null"
        Else
            fontItalicStr = LCase(CStr(cf.Font.Italic))
        End If

        tempStr = tempStr & "          ""Font"": {" & vbCrLf
        tempStr = tempStr & "              ""Name"": """ & cf.Font.Name & """," & vbCrLf
        tempStr = tempStr & "              ""Size"": " & fontSizeStr & "," & vbCrLf
        tempStr = tempStr & "              ""Color"": " & fontColorHex & "," & vbCrLf
        tempStr = tempStr & "              ""Bold"": " & fontBoldStr & "," & vbCrLf
        tempStr = tempStr & "              ""Italic"": " & fontItalicStr & vbCrLf
        tempStr = tempStr & "          }" & vbCrLf

        tempStr = tempStr & "        }"
        If i < ws.Cells.FormatConditions.Count Then
            tempStr = tempStr & "," & vbCrLf
        End If
    Next i

    If Right(tempStr, 2) = "," & vbCrLf Then tempStr = Left(tempStr, Len(tempStr) - 2)
    jsonCf = jsonCf & tempStr

    ConvertConditionalFormattingToJSON = jsonCf
End Function

' Function to convert data validations to JSON
Private Function ConvertDataValidationsToJSON(ws As Worksheet) As String
    Dim jsonDv As String
    Dim dv As Validation
    Dim cell As Range
    Dim firstDv As Boolean
    Dim dvRange As Range

    jsonDv = ""
    firstDv = True

    On Error Resume Next
    Set dvRange = ws.UsedRange.SpecialCells(xlCellTypeAllValidation)
    On Error GoTo 0

    If Not dvRange Is Nothing Then
        For Each cell In dvRange
            Set dv = cell.Validation
            If Not dv Is Nothing Then ' Check if the Validation object is set
                If dv.Type <> -4142 Then ' xlValidateNone is -4142
                    If Not firstDv Then
                        jsonDv = jsonDv & "," & vbCrLf
                    End If
                    firstDv = False

                    jsonDv = jsonDv & "        {" & vbCrLf
                    jsonDv = jsonDv & "          ""Address"": """ & cell.address & """," & vbCrLf
                    jsonDv = jsonDv & "          ""Type"": """ & dv.Type & """," & vbCrLf
                    jsonDv = jsonDv & "          ""AlertStyle"": """ & dv.alertStyle & """," & vbCrLf
                    jsonDv = jsonDv & "          ""Formula1"": """ & EscapeJsonString(dv.formula1) & """," & vbCrLf
                    jsonDv = jsonDv & "          ""Formula2"": """ & EscapeJsonString(dv.formula2) & """," & vbCrLf
                    jsonDv = jsonDv & "          ""ShowInputMessage"": " & BooleanToLowercase(dv.showInput) & "," & vbCrLf
                    jsonDv = jsonDv & "          ""InputTitle"": """ & EscapeJsonString(dv.InputTitle) & """," & vbCrLf
                    jsonDv = jsonDv & "          ""InputMessage"": """ & EscapeJsonString(dv.InputMessage) & """," & vbCrLf
                    jsonDv = jsonDv & "          ""ShowErrorMessage"": " & BooleanToLowercase(dv.showError) & "," & vbCrLf
                    jsonDv = jsonDv & "          ""ErrorTitle"": """ & EscapeJsonString(dv.ErrorTitle) & """," & vbCrLf
                    jsonDv = jsonDv & "          ""ErrorMessage"": """ & EscapeJsonString(dv.ErrorMessage) & """" & vbCrLf
                    jsonDv = jsonDv & "        }"
                End If
            End If
        Next cell
    End If

    ConvertDataValidationsToJSON = jsonDv
End Function


' Helper function to convert color to HEX in RGB format
Private Function ColorToHex(colorValue As Long) As String
    Dim r As Long
    Dim g As Long
    Dim b As Long
    
    ' Extract the Red, Green, and Blue components
    r = colorValue Mod 256
    g = (colorValue \ 256) Mod 256
    b = (colorValue \ 65536) Mod 256
    
    ' Convert to HEX and format as a string
    ColorToHex = "#" & Right("00" & Hex(r), 2) & Right("00" & Hex(g), 2) & Right("00" & Hex(b), 2)
End Function


' Function to convert boolean values to lowercase strings
Private Function BooleanToLowercase(value As Boolean) As String
    If value = True Then
        BooleanToLowercase = "true"
    Else
        BooleanToLowercase = "false"
    End If
End Function


