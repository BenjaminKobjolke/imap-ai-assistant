@echo off
if "%~1"=="" (
    uv run main.py --meetings today
) else (
    uv run main.py --meetings %1
)
