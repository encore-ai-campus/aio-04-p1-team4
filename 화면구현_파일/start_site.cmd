@echo off
setlocal
title LUNCH RUN local server
cd /d "%~dp0"
echo LUNCH RUN: http://localhost:5500
echo Keep this window open while using the site.
set "LUNCH_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%LUNCH_PYTHON%" (
  "%LUNCH_PYTHON%" "%~dp0examples\kakao-map\serve.py"
  goto finish
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0examples\kakao-map\serve.py"
  goto finish
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0examples\kakao-map\serve.py"
  goto finish
)
echo Python 3 is required to run the local server.
:finish
pause
