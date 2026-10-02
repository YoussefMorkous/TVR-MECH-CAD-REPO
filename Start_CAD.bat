@echo off
cd /d "%~dp0"
py -3 tools\cad.py gui
if errorlevel 1 pause
