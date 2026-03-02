@echo off
echo Running tests...
call uv run pytest tests/ -v
pause
