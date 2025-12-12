#!/bin/bash

# Monitor and auto-restart ngrok tunnel
# This script checks if ngrok is running and restarts it if needed

NGROK_PORT=5000
CHECK_INTERVAL=30  # Check every 30 seconds
MAX_RETRIES=5
RETRY_DELAY=5

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR${NC} $1"
}

warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING${NC} $1"
}

# Start ngrok
start_ngrok() {
    log "Starting ngrok tunnel on port $NGROK_PORT..."
    ngrok http $NGROK_PORT > /tmp/ngrok.log 2>&1 &
    NGROK_PID=$!
    log "ngrok started with PID: $NGROK_PID"
    sleep 3
}

# Check if ngrok is running
check_ngrok() {
    if pgrep -f "ngrok http $NGROK_PORT" > /dev/null; then
        return 0  # Running
    else
        return 1  # Not running
    fi
}

# Get ngrok URL
get_ngrok_url() {
    # Try to get URL from ngrok API
    curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"[^"]*' | head -1 | cut -d'"' -f4
}

# Kill existing ngrok processes
cleanup_ngrok() {
    log "Cleaning up existing ngrok processes..."
    pkill -f "ngrok http $NGROK_PORT" 2>/dev/null
    sleep 2
}

# Main monitor loop
log "=========================================="
log "ngrok Tunnel Monitor Started"
log "=========================================="
log "Monitoring port: $NGROK_PORT"
log "Check interval: $CHECK_INTERVAL seconds"
log "Press Ctrl+C to stop"
log ""

# Kill any existing ngrok processes first
cleanup_ngrok

# Start initial tunnel
start_ngrok

while true; do
    sleep $CHECK_INTERVAL
    
    if check_ngrok; then
        # Get current URL
        URL=$(get_ngrok_url)
        if [ -n "$URL" ]; then
            log "✓ ngrok tunnel active: $URL"
        else
            log "✓ ngrok tunnel active (URL not yet available)"
        fi
    else
        warning "ngrok tunnel disconnected! Attempting restart..."
        
        # Retry logic
        for ((i=1; i<=MAX_RETRIES; i++)); do
            log "Restart attempt $i/$MAX_RETRIES..."
            cleanup_ngrok
            start_ngrok
            
            sleep 3
            if check_ngrok; then
                URL=$(get_ngrok_url)
                log "✓ ngrok tunnel restored successfully!"
                if [ -n "$URL" ]; then
                    log "URL: $URL"
                fi
                break
            else
                if [ $i -lt $MAX_RETRIES ]; then
                    warning "Restart attempt $i failed, retrying in ${RETRY_DELAY}s..."
                    sleep $RETRY_DELAY
                else
                    error "Failed to restart ngrok after $MAX_RETRIES attempts"
                    error "Please check ngrok installation or manually restart"
                fi
            fi
        done
    fi
done
