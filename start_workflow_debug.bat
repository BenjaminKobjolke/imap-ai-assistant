@echo off
call uv run python main.py --config settings_debug.json --workflow rtm_todos --auto-accept %*
