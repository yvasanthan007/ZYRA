Set-Location 'c:\Users\Rakshanaa\Project\ZYRA'
$env:PYTHONUNBUFFERED = '1'
$p = Start-Process -FilePath python -ArgumentList '-m','uvicorn','backend.server:app','--port','8765' -RedirectStandardOutput 'server_out.log' -RedirectStandardError 'server_err.log' -PassThru
Start-Sleep 30
Get-Content 'server_err.log' -Tail 20
python _e2e_dns_test.py
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
