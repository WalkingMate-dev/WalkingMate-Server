$python = 'C:\androidApp\server\.venv\Scripts\python.exe'
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -eq $python
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Write-Host 'Stopped python processes launched from server venv.'
