@echo off
if "%~1"=="" (
    uv run main.py --todays-meetings
) else (
    uv run main.py --todays-meeting %1
)
