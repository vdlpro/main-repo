while (Get-Process -Id 55832 -ErrorAction SilentlyContinue) {
  Start-Sleep -Seconds 15
}
Set-Location 'C:\Users\aweec\Documents\Analyse Full Ereferer'
$env:AUDIT_BATCH_INDEX='4'
$env:AUDIT_BATCH_SIZE='2000'
$env:AUDIT_WORKERS='48'
$env:AUDIT_SECOND_PASS_WORKERS='16'
$env:AUDIT_SITE_BUDGET_SECONDS='60'
Start-Process -FilePath 'C:\Users\aweec\AppData\Local\Programs\Python\Python313\python.exe' -ArgumentList 'scripts\audit_sitemaps.py' -WorkingDirectory 'C:\Users\aweec\Documents\Analyse Full Ereferer' -RedirectStandardOutput 'C:\Users\aweec\Documents\Analyse Full Ereferer\data\state\sitemap_audit\run-batch-0004.log' -RedirectStandardError 'C:\Users\aweec\Documents\Analyse Full Ereferer\data\state\sitemap_audit\run-batch-0004.err.log' -WindowStyle Hidden
