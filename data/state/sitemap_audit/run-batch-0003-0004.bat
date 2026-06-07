@echo off
cd /d "C:\Users\aweec\Documents\Analyse Full Ereferer"
set AUDIT_BATCH_SIZE=2000
set AUDIT_WORKERS=48
set AUDIT_SECOND_PASS_WORKERS=16
set AUDIT_SITE_BUDGET_SECONDS=60
set AUDIT_BATCH_INDEX=3
python scripts\audit_sitemaps.py > "C:\Users\aweec\Documents\Analyse Full Ereferer\data\state\sitemap_audit\run-batch-0003.log" 2>&1
set AUDIT_BATCH_INDEX=4
python scripts\audit_sitemaps.py > "C:\Users\aweec\Documents\Analyse Full Ereferer\data\state\sitemap_audit\run-batch-0004.log" 2>&1
