Imports System
Imports System.Collections.Generic

Module Module1
    Sub Main()
        Dim app As New Application()
        app.Run()
    End Sub
End Module

Public Class Application
    Private ReadOnly items As New List(Of String)

    Public Sub Run()
        LoadData()
        ProcessData()
    End Sub

    Private Sub LoadData()
        items.Add("item1")
        items.Add("item2")
    End Sub

    Private Function ProcessData() As Boolean
        For Each item In items
            Console.WriteLine(item)
        Next
        Return True
    End Function
End Class
