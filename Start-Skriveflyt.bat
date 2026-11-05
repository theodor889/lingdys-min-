@echo off
chcp 65001 > nul
cd /d "%~dp0"
py -3 main.py
if errorlevel 1 (
  echo.
  echo Skriveflyt kunne ikke starte. Installer Python 3 for Windows fra python.org.
  pause
)

