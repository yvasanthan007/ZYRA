Set-Location 'c:\Users\Rakshanaa\Project\ZYRA'
$env:PYTHONUNBUFFERED = '1'
$p = Start-Process -FilePath python -ArgumentList '-m','uvicorn','backend.server:app','--port','8766' -RedirectStandardOutput 'server_out.log' -RedirectStandardError 'server_err.log' -PassThru
Set-Content -Path 'server_pid.txt' -Value $p.Id
Start-Sleep 30
Get-Content 'server_out.log' -Tail 6
