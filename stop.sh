#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PID_FILE="$SCRIPT_DIR/bot.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Bot may not be running."
    exit 1
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping bot (PID: $PID)..."
    kill "$PID"
    rm -f "$PID_FILE"
    echo "Bot stopped successfully."
else
    echo "Process $PID is not running. Cleaning up stale PID file."
    rm -f "$PID_FILE"
fi
