@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
)
".venv\Scripts\python.exe" -c "import streamlit,pdfplumber,openpyxl,pandas" >nul 2>&1
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Falha na instalacao. Consulte README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1
pause
