#!/bin/bash
# Polymarket Copy Trading Bot - Linux/macOS Runner Script
# This script helps beginners run the bot easily

set -e

echo "========================================"
echo "Polymarket Copy Trading Bot"
echo "========================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "[ERROR] .env file not found!"
    echo ""
    echo "Please create a .env file first:"
    echo "  1. Copy .env.example to .env"
    echo "     cp .env.example .env"
    echo "  2. Open .env in a text editor"
    echo "  3. Fill in your configuration values"
    echo "  4. See docs/02_SETUP_GUIDE.md for help"
    echo ""
    exit 1
fi

# Validate configuration
echo "[1/3] Validating configuration..."
echo ""
cargo run --release --bin validate_setup || {
    echo ""
    echo "Configuration check failed! Please fix the errors above."
    echo "See docs/06_TROUBLESHOOTING.md for help."
    echo ""
    exit 1
}

echo ""
echo "[2/3] Building bot (this may take a few minutes on first run)..."
echo ""
cargo build --release || {
    echo ""
    echo "Build failed! Please check the errors above."
    echo "See docs/06_TROUBLESHOOTING.md for help."
    echo ""
    exit 1
}

echo ""
echo "[3/3] Starting bot..."
echo ""
echo "Press Ctrl+C to stop the bot"
echo ""

# Run the bot
cargo run --release

# If we get here, the bot exited
echo ""
echo "Bot has stopped."

