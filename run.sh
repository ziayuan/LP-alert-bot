#!/bin/bash

# Simple run script for the background
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/bot.pid"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Bot is already running (PID: $(cat "$PID_FILE"))."
    exit 1
fi

# Source virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run the bot in the background with nohup
nohup python3 main.py > bot.log 2>&1 &

# Write PID file
echo $! > "$PID_FILE"

echo "PancakeSwap V3 Monitor Bot started in the background."
echo "PID: $!"
echo "View logs with: tail -f bot.log"
