@echo off
cd /d "%~dp0khj_backend"
"%~dp0khj_backend\.venv-db\Scripts\python.exe" run_map_site.py
pause
