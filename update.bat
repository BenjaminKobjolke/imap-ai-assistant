@echo off
echo ============================================
echo  IMAP AI Assistant - Update Dependencies
echo ============================================

where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: uv is not installed or not in PATH.
    pause
    exit /b 1
)

echo.
echo Upgrading lock file...
call uv lock --upgrade

echo.
echo Syncing dependencies...
call uv sync --all-groups

echo.
echo Running ruff...
call uv run ruff check src/ main.py

echo.
echo Running mypy...
call uv run mypy src/ main.py

echo.
echo Running tests...
call uv run pytest tests/ -v

echo.
echo ============================================
echo  Update complete!
echo ============================================
pause
