@echo off
"%PREFIX%\python.exe" "%PREFIX%\app_payload\install_desktop.py"
if errorlevel 1 exit /b 1
