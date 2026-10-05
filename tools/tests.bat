@echo off
echo Running tests...
call uv run pytest tests/ -v
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
