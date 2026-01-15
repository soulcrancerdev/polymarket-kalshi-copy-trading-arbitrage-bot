@echo off
REM Polymarket Copy Trading Bot - Windows Runner Script
REM This script helps beginners run the bot easily on Windows

echo ========================================
echo Polymarket Copy Trading Bot
echo ========================================
echo.

REM Check if .env exists
if not exist .env (
    echo [ERROR] .env file not found!
    echo.
    echo Please create a .env file first:
    echo   1. Copy .env.example to .env
    echo   2. Open .env in a text editor
    echo   3. Fill in your configuration values
    echo   4. See docs/02_SETUP_GUIDE.md for help
    echo.
    pause
    exit /b 1
)

REM Validate configuration
echo [1/3] Validating configuration...
echo.
cargo run --release --bin validate_setup
if %errorlevel% neq 0 (
    echo.
    echo Configuration check failed! Please fix the errors above.
    echo See docs/06_TROUBLESHOOTING.md for help.
    echo.
    pause
    exit /b 1
)

echo.
echo [2/3] Building bot (this may take a few minutes on first run)...
echo.
cargo build --release
if %errorlevel% neq 0 (
    echo.
    echo Build failed! Please check the errors above.
    echo See docs/06_TROUBLESHOOTING.md for help.
    echo.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting bot...
echo.
echo Press Ctrl+C to stop the bot
echo.

REM Run the bot
cargo run --release

REM If we get here, the bot exited
echo.
echo Bot has stopped.
pause

