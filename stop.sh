#!/bin/bash
cd "$(dirname "$0")"

# Kill by PID file if it exists
if [ -f bot.pid ]; then
    PID=$(cat bot.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping bot (PID: $PID)..."
        kill "$PID"
        sleep 2
        kill -9 "$PID" 2>/dev/null
    fi
    rm -f bot.pid
fi

# Also kill any orphaned instances by name
pkill -f "python.*main\.py" 2>/dev/null

echo "Bot stopped."
