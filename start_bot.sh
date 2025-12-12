#!/bin/bash

# Start both the Flask server and ngrok monitor
# Usage: ./start_bot.sh

PROJECT_DIR="/Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  GolfoStreams Bot - Startup Script      ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

cd "$PROJECT_DIR" || exit 1

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ ERROR: .env file not found in $PROJECT_DIR"
    exit 1
fi

echo -e "${GREEN}✓${NC} Project directory: $PROJECT_DIR"
echo -e "${GREEN}✓${NC} .env file found"
echo ""

# Kill any existing processes
echo "Cleaning up any existing processes..."
pkill -f "python.*server.py" 2>/dev/null || true
pkill -f "ngrok http" 2>/dev/null || true
sleep 2

echo ""
echo -e "${BLUE}Starting services...${NC}"
echo ""

# Start Flask server in background
echo -e "${GREEN}[1/2]${NC} Starting Flask server..."
nohup python server.py > /tmp/flask_server.log 2>&1 &
FLASK_PID=$!
echo -e "${GREEN}✓${NC} Flask server started (PID: $FLASK_PID)"
echo "    Logs: tail -f /tmp/flask_server.log"
sleep 2

# Start ngrok monitor in background
echo ""
echo -e "${GREEN}[2/2]${NC} Starting ngrok tunnel monitor..."
nohup ./monitor_ngrok.sh > /tmp/ngrok_monitor.log 2>&1 &
MONITOR_PID=$!
echo -e "${GREEN}✓${NC} ngrok monitor started (PID: $MONITOR_PID)"
echo "    Logs: tail -f /tmp/ngrok_monitor.log"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Services Running Successfully! 🚀      ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "Services running:"
echo "  • Flask Server: http://localhost:5000"
echo "  • ngrok Monitor: Auto-restarting tunnels"
echo ""
echo "View logs:"
echo "  • Flask:  tail -f /tmp/flask_server.log"
echo "  • ngrok:  tail -f /tmp/ngrok_monitor.log"
echo ""
echo "To stop all services:"
echo "  pkill -f 'python.*server.py' && pkill -f 'ngrok http' && pkill -f 'monitor_ngrok'"
echo ""
echo "Active PIDs:"
echo "  • Flask: $FLASK_PID"
echo "  • Monitor: $MONITOR_PID"
