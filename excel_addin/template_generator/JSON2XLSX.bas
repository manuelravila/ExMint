Attribute VB_Name = "JSON2XLSX"
Option Explicit

' Main function to convert JSON to XLSX
Public Sub JSON2XLSX()
    Dim jsonString As String
    Dim jsonObject As Object
    Dim wb As Workbook
    Dim ws As Worksheet
    Dim sheet As Object
    Dim i As Long
    Dim filePath As String
    
    ' Allow user to select JSON file
    filePath = SelectJSONFile()
    If filePath = "" Then
        MsgBox "No file selected. Operation cancelled.", vbInformation
        Exit Sub
    End If
    
  ' Parse JSON string
    Set jsonObject = ParseJSON(jsonString)
    
    ' Create a new workbook
    Set wb = Application.Workbooks.Add
    
    ' Rename the first sheet and delete others if any
    wb.Sheets(1).Name = "TempSheet"
    Application.DisplayAlerts = False
    For i = wb.Sheets.Count To 2 Step -1
        wb.Sheets(i).Delete
    Next i
    Application.DisplayAlerts = True
    
    ' Create sheets and populate data
    For Each sheet In jsonObject("Sheets")
        If wb.Sheets.Count = 1 And wb.Sheets(1).Name = "TempSheet" Then
            ' Rename the existing sheet instead of adding a new one
            Set ws = wb.Sheets(1)
            ws.Name = sheet("Name")
        Else
            Set ws = wb.Sheets.Add(After:=wb.Sheets(wb.Sheets.Count))
            ws.Name = sheet("Name")
        End If
        
        ' Create ListObjects
        CreateListObjects ws, sheet("ListObjects")
        
        ' Create PivotTables
        CreatePivotTables ws, sheet("PivotTables")
        
        ' Set OtherCells
        SetOtherCells ws, sheet("OtherCells")
        
        ' Apply Conditional Formatting
        ApplyConditionalFormatting ws, sheet("ConditionalFormatting")
    Next sheet
    
    ' Delete the temporary sheet if it still exists
    Application.DisplayAlerts = False
    On Error Resume Next
    wb.Sheets("TempSheet").Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    
    ' Create Custom Named Ranges
    CreateCustomNamedRanges wb, jsonObject("CustomNamedRanges")
    
    MsgBox "Workbook created successfully!", vbInformation
End Sub

' Function to allow user to select JSON file
Private Function SelectJSONFile() As String
    Dim fd As Office.FileDialog
    
    Set fd = Application.FileDialog(msoFileDialogFilePicker)
    
    With fd
        .Title = "Select JSON File"
        .Filters.Clear
        .Filters.Add "JSON Files", "*.json"
        .AllowMultiSelect = False
        
        If .Show = -1 Then
            SelectJSONFile = .SelectedItems(1)
        Else
            SelectJSONFile = ""
        End If
    End With
End Function

' Function to read JSON file
Private Function ReadJSONFile(filePath As String) As String
    Dim fso As Object
    Dim jsonFile As Object
    
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set jsonFile = fso.OpenTextFile(filePath, 1)
    
    ReadJSONFile = jsonFile.ReadAll
    jsonFile.Close
End Function

Private Function ParseJSON(jsonString As String) As Object
    Dim json As Variant
    
    ParseJSONObject json, jsonString, 1
    
    If TypeName(json) = "Dictionary" Then
        Set ParseJSON = json
    Else
        Set ParseJSON = CreateObject("Scripting.Dictionary")
        ParseJSON.Add "root", json
    End If
End Function

Private Sub ParseJSONObject(ByRef obj As Variant, ByVal jsonString As String, ByRef index As Long)
    Dim key As String
    Dim value As Variant
    Dim arrayIndex As Long
    
    If TypeName(obj) <> "Dictionary" Then
        Set obj = CreateObject("Scripting.Dictionary")
    End If
    
    Do While index <= Len(jsonString)
        Select Case Mid(jsonString, index, 1)
            Case "{"
                index = index + 1
                Dim newObj As Object
                Set newObj = CreateObject("Scripting.Dictionary")
                ParseJSONObject newObj, jsonString, index
                If TypeName(obj) = "Collection" Then
                    obj.Add newObj
                End If
            Case "["
                index = index + 1
                Dim newArray As Collection
                Set newArray = New Collection
                ParseJSONArray newArray, jsonString, index
                If TypeName(obj) = "Dictionary" Then
                    If obj.Exists(key) Then
                        Set obj(key) = newArray
                    Else
                        obj.Add key, newArray
                    End If
                ElseIf TypeName(obj) = "Collection" Then
                    obj.Add newArray
                End If
            Case """"
                key = ParseJSONString(jsonString, index)
                index = index + 1 ' Skip the colon
                If Mid(jsonString, index, 1) = "{" Then
                    Set value = CreateObject("Scripting.Dictionary")
                    index = index + 1
                    ParseJSONObject value, jsonString, index
                ElseIf Mid(jsonString, index, 1) = "[" Then
                    index = index + 1
                    ParseJSONArray value, jsonString, index
                Else
                    value = ParseJSONValue(jsonString, index)
                End If
                If TypeName(obj) = "Dictionary" Then
                    If obj.Exists(key) Then
                        obj(key) = value ' Update existing key
                    Else
                        obj.Add key, value ' Add new key
                    End If
                End If
            Case "}"
                index = index + 1
                Exit Do
            Case ","
                index = index + 1
            Case Else
                index = index + 1
        End Select
    Loop
End Sub

Private Sub ParseJSONArray(ByRef arr As Variant, ByVal jsonString As String, ByRef index As Long)
    Dim value As Variant
    
    If TypeName(arr) <> "Collection" Then
        Set arr = New Collection
    End If
    
    Do While index <= Len(jsonString)
        Select Case Mid(jsonString, index, 1)
            Case "{"
                Set value = CreateObject("Scripting.Dictionary")
                index = index + 1
                ParseJSONObject value, jsonString, index
                arr.Add value
            Case "["
                Dim newArray As New Collection
                index = index + 1
                ParseJSONArray newArray, jsonString, index
                arr.Add newArray
            Case "]"
                index = index + 1
                Exit Do
            Case ","
                index = index + 1
            Case Else
                value = ParseJSONValue(jsonString, index)
                arr.Add value
        End Select
    Loop
End Sub

Private Function ParseJSONString(ByVal jsonString As String, ByRef index As Long) As String
    Dim startIndex As Long
    Dim endIndex As Long
    
    index = index + 1 ' Skip the opening quote
    startIndex = index
    
    Do While index <= Len(jsonString)
        If Mid(jsonString, index, 1) = """" And Mid(jsonString, index - 1, 1) <> "\" Then
            endIndex = index - 1
            Exit Do
        End If
        index = index + 1
    Loop
    
    ParseJSONString = Mid(jsonString, startIndex, endIndex - startIndex + 1)
    index = index + 1 ' Skip the closing quote
End Function

Private Function ParseJSONValue(ByVal jsonString As String, ByRef index As Long) As Variant
    Dim startIndex As Long
    Dim endIndex As Long
    Dim valueString As String
    
    startIndex = index
    
    Do While index <= Len(jsonString)
        If InStr(",}]", Mid(jsonString, index, 1)) > 0 Then
            endIndex = index - 1
            Exit Do
        End If
        index = index + 1
    Loop
    
    valueString = Trim(Mid(jsonString, startIndex, endIndex - startIndex + 1))
    
    If IsNumeric(valueString) Then
        ParseJSONValue = CDbl(valueString)
    ElseIf valueString = "true" Then
        ParseJSONValue = True
    ElseIf valueString = "false" Then
        ParseJSONValue = False
    ElseIf valueString = "null" Then
        ParseJSONValue = Null
    Else
        ParseJSONValue = valueString
    End If
End Function

' Function to create ListObjects
Private Sub CreateListObjects(ws As Worksheet, listObjects As Object)
    Dim lo As Object
    Dim rng As Range
    Dim col As Object
    Dim i As Long, j As Long
    
    For Each lo In listObjects
        ' Set the range for the ListObject
        Set rng = ws.Range(lo("StartingCell"))
        Set rng = rng.Resize(1, lo("Columns").Count)
        
        ' Add headers
        For i = 1 To lo("Columns").Count
            rng.Cells(1, i).value = lo("Columns")(i - 1)("Header")
        Next i
        
        ' Add data rows
        For i = 1 To lo("Columns")(0)("Rows").Count
            Set rng = rng.Resize(rng.Rows.Count + 1, rng.Columns.Count)
            For j = 1 To lo("Columns").Count
                rng.Cells(rng.Rows.Count, j).value = lo("Columns")(j - 1)("Rows")(i - 1)
            Next j
        Next i
        
        ' Create ListObject
        ws.listObjects.Add(xlSrcRange, rng, , xlYes).Name = lo("Name")
        
        ' Set ListObject style
        ws.listObjects(lo("Name")).TableStyle = lo("ColorStyle")
        
        ' Set column widths and formulas
        For i = 1 To lo("Columns").Count
            ws.Columns(rng.Column + i - 1).ColumnWidth = lo("Columns")(i - 1)("Width")
            If lo("Columns")(i - 1)("Formula") <> "" Then
                ws.listObjects(lo("Name")).ListColumns(i).DataBodyRange.formula = lo("Columns")(i - 1)("Formula")
            End If
        Next i
    Next lo
End Sub

' Function to create PivotTables
Private Sub CreatePivotTables(ws As Worksheet, pivotTables As Object)
    Dim pt As Object
    Dim pc As PivotCache
    Dim ptTable As PivotTable
    Dim pf As PivotField
    Dim i As Long
    
    For Each pt In pivotTables
        ' Create PivotCache (assuming data is in a ListObject named "Data")
        Set pc = ThisWorkbook.PivotCaches.Create(xlDatabase, ws.listObjects("Data").Range)
        
        ' Create PivotTable
        Set ptTable = pc.CreatePivotTable(ws.Range(pt("StartingCell")), pt("Name"))
        
        ' Add Row Fields
        For i = 1 To pt("RowFields").Count
            Set pf = ptTable.PivotFields(pt("RowFields")(i - 1)("Name"))
            pf.Orientation = xlRowField
            pf.Position = i
            pf.Subtotals(1) = pt("RowFields")(i - 1)("Subtotals")
            pf.LayoutForm = pt("RowFields")(i - 1)("LayoutForm")
        Next i
        
        ' Add Column Fields
        For i = 1 To pt("ColumnFields").Count
            Set pf = ptTable.PivotFields(pt("ColumnFields")(i - 1)("Name"))
            pf.Orientation = xlColumnField
            pf.Position = i
        Next i
        
        ' Add Value Fields
        For i = 1 To pt("ValueFields").Count
            With ptTable.AddDataField(ptTable.PivotFields(pt("ValueFields")(i - 1)("Name")))
                .Function = pt("ValueFields")(i - 1)("SummarizedBy")
                .numberFormat = pt("ValueFields")(i - 1)("NumberFormat")
                .Caption = pt("ValueFields")(i - 1)("CustomName")
            End With
        Next i
        
        ' Set PivotTable style
        ptTable.TableStyle2 = pt("ColorStyle")
    Next pt
End Sub

' Function to set other cells
Private Sub SetOtherCells(ws As Worksheet, otherCells As Object)
    Dim cell As Object
    
    For Each cell In otherCells
        ws.Range(cell("Address")).formula = cell("Formula")
    Next cell
End Sub

' Function to apply conditional formatting
Private Sub ApplyConditionalFormatting(ws As Worksheet, conditionalFormatting As Object)
    Dim cf As Object
    Dim fmt As formatCondition
    
    For Each cf In conditionalFormatting
        Set fmt = ws.Range(cf("AppliesTo")).FormatConditions.Add(Type:=cf("Type"), formula1:=cf("Formula"))
        
        With fmt
            .Interior.Color = cf("Interior")("Color")
            .Interior.Pattern = cf("Interior")("Pattern")
        End With
    Next cf
End Sub

' Function to create custom named ranges
Private Sub CreateCustomNamedRanges(wb As Workbook, customNamedRanges As Object)
    Dim nr As Object
    
    For Each nr In customNamedRanges
        wb.Names.Add Name:=nr("Name"), RefersTo:=nr("RefersTo")
    Next nr
End Sub
