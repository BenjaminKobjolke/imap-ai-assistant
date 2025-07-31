@echo off
echo Installing dependencies...
call python -m venv venv
call venv\Scripts\ activate
call pip install -r requirements.txt
echo Installation complete.
pause
