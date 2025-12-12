#!/bin/bash
# Watchdog script to keep gateway_bot.py running

BOT_SCRIPT="/Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams/gateway_bot.py"
PYTHON_PATH="/Users/cristianespinosa/opt/anaconda3/envs/tensor/bin/python"
LOG_FILE="/tmp/gateway_bot.log"

echo "Starting GolfoBot watchdog..."

while true; do
    # Check if bot is running
    if ! pgrep -f "gateway_bot.py" > /dev/null; then
        echo "[$(date)] Bot not running, starting..."
        $PYTHON_PATH $BOT_SCRIPT &> $LOG_FILE &
        sleep 10
    fi
    
    # Check if bot is responding (debug endpoint)
    if ! curl -s -m 2 http://127.0.0.1:8765/ > /dev/null 2>&1; then
        echo "[$(date)] Bot not responding, restarting..."
        pkill -f "gateway_bot.py"
        sleep 3
        $PYTHON_PATH $BOT_SCRIPT &> $LOG_FILE &
        sleep 10
    fi
    
    # Wait before next check
    sleep 30
done
