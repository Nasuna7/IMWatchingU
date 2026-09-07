@echo off
setlocal
rem ============================================================
rem  Screen OCR - QQ Sender Tool  (screen-qq-ocr)
rem  All messages are ASCII-only on purpose: this .bat is parsed
rem  by cmd.exe with the system codepage (GBK on Chinese Windows),
rem  so any non-ASCII text can corrupt the command flow.
rem ============================================================
cd /d "%~dp0"

echo ============================================
echo   Screen OCR - QQ Sender
echo   Web page : http://127.0.0.1:8765
echo   Close this window or press Ctrl+C to stop
echo ============================================
echo.

where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found in PATH.
    echo         Please install Node.js first, then run this file again.
    pause
    exit /b 1
)

echo [OK] Node.js found:
node --version
echo.

if not exist "public\vendor\tesseract.min.js" (
    echo [INFO] OCR dependencies not found. Running setup script...
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1"
    if errorlevel 1 (
        echo [ERROR] Setup failed. Please check your network connection,
        echo         or run  scripts\setup.ps1  manually and check the output.
        pause
        exit /b 1
    )
)

echo [OK] Starting server on http://127.0.0.1:8765 ...
echo      Keep this window open while using the tool.
echo.
node server.js
if errorlevel 1 (
    echo.
    echo [ERROR] Server exited with an error. See the messages above.
    pause
)
