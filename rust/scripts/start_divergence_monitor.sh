#!/bin/bash
# Start the divergence monitor in a screen session
#
# Usage:
#   ./start_divergence_monitor.sh        # Start in screen
#   ./start_divergence_monitor.sh --fg   # Run in foreground
#   ./start_divergence_monitor.sh --stop # Stop the screen session
#
# To attach to running screen: screen -r divergence
# To detach from screen: Ctrl+A, D

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."  # Go to a_poly_trade_optimized root for uv

SCREEN_NAME="divergence"
PYTHON_SCRIPT="rust_clob_client/scripts/divergence_server.py"

# Use uv run
PYTHON="uv run python3"

case "$1" in
    --stop)
        echo "Stopping divergence monitor..."
        screen -S "$SCREEN_NAME" -X quit 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "Stopped."
        else
            echo "Not running."
        fi
        ;;
    --fg)
        echo "Running in foreground (Ctrl+C to stop)..."
        echo "Dashboard: http://localhost:8765"
        $PYTHON "$PYTHON_SCRIPT"
        ;;
    --status)
        if screen -list | grep -q "$SCREEN_NAME"; then
            echo "Running in screen '$SCREEN_NAME'"
            echo "Dashboard: http://localhost:8765"
            echo ""
            echo "To attach: screen -r $SCREEN_NAME"
            echo "To stop:   $0 --stop"
        else
            echo "Not running."
            echo "To start:  $0"
        fi
        ;;
    *)
        # Check if already running
        if screen -list | grep -q "$SCREEN_NAME"; then
            echo "Already running in screen '$SCREEN_NAME'"
            echo "Dashboard: http://localhost:8765"
            echo ""
            echo "To attach: screen -r $SCREEN_NAME"
            echo "To stop:   $0 --stop"
            exit 0
        fi

        echo "Starting divergence monitor in screen session '$SCREEN_NAME'..."
        screen -dmS "$SCREEN_NAME" $PYTHON "$PYTHON_SCRIPT"

        sleep 2

        if screen -list | grep -q "$SCREEN_NAME"; then
            echo "Started successfully!"
            echo ""
            echo "Dashboard: http://localhost:8765"
            echo ""
            echo "Commands:"
            echo "  Attach to screen:  screen -r $SCREEN_NAME"
            echo "  Detach from screen: Ctrl+A, D"
            echo "  Stop monitor:      $0 --stop"
            echo "  Check status:      $0 --status"
        else
            echo "Failed to start. Try running in foreground for debugging:"
            echo "  $0 --fg"
            exit 1
        fi
        ;;
esac
