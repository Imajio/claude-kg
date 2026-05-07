@echo off
echo ================================
echo  Claude to Obsidian KG Server
echo ================================
echo.

REM Load environment if needed
if "%ANTHROPIC_API_KEY%"=="" (
    echo WARNING: ANTHROPIC_API_KEY not set!
    echo Set it in System Environment Variables.
    echo.
)

echo Starting server on http://127.0.0.1:7842
echo Press Ctrl+C to stop.
echo.

python "%~dp0server.py"
pause
