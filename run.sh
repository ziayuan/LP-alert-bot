#!/bin/bash
cd "$(dirname "$0")"

# Kill ANY existing instance first (by name, not just PID file)
pkill -f "python.*main\.py" 2>/dev/null
sleep 1

# Clean up stale PID file
rm -f bot.pid

# Activate venv
source ../venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null

# Start in background
nohup python3 main.py >> /dev/null 2>&1 &
echo $! > bot.pid

echo "PancakeSwap V3 Monitor Bot started in the background."
echo "PID: $(cat bot.pid)"
echo "View logs with: tail -f bot.log"
