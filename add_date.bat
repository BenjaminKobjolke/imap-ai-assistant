@echo off
if "%~1"=="" (
    echo Usage: add_date TITLE [DATE] [START[-END]] [@CALENDAR]
    echo Example: add_date "Team Standup" 05.03.2026 9-10 @Work
) else (
    uv run main.py --add-date %*
)
