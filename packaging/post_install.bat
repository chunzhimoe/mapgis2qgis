@echo off
"%PREFIX%\python.exe" "%PREFIX%\app_payload\install_desktop.py" > "%PREFIX%\mapgis-post-install.log" 2>&1
set "MAPGIS_INSTALL_EXIT=%ERRORLEVEL%"
type "%PREFIX%\mapgis-post-install.log"
exit /b %MAPGIS_INSTALL_EXIT%
