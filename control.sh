#!/bin/bash

# GolfoBot Control Center - Manage bot services easily

PROJECT_DIR="/Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams"
cd "$PROJECT_DIR" || exit 1

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_menu() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  GolfoBot Control Center                 ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "1) Start bot (server + ngrok monitor)"
    echo "2) Stop all services"
    echo "3) Restart bot"
    echo "4) View Flask logs"
    echo "5) View ngrok monitor logs"
    echo "6) Check service status"
    echo "7) Manually restart ngrok"
    echo "8) Exit"
    echo ""
}

check_status() {
    echo -e "${BLUE}Service Status:${NC}"
    
    if pgrep -f "python.*server.py" > /dev/null; then
        echo -e "  ${GREEN}✓${NC} Flask server is running"
        FLASK_PID=$(pgrep -f "python.*server.py")
        echo "    PID: $FLASK_PID"
    else
        echo -e "  ${RED}✗${NC} Flask server is NOT running"
    fi
    
    if pgrep -f "ngrok http" > /dev/null; then
        echo -e "  ${GREEN}✓${NC} ngrok tunnel is active"
        NGROK_PID=$(pgrep -f "ngrok http")
        echo "    PID: $NGROK_PID"
        # Try to get URL
        URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"[^"]*' | head -1 | cut -d'"' -f4)
        if [ -n "$URL" ]; then
            echo "    URL: $URL"
        fi
    else
        echo -e "  ${RED}✗${NC} ngrok tunnel is NOT running"
    fi
    
    if pgrep -f "monitor_ngrok" > /dev/null; then
        echo -e "  ${GREEN}✓${NC} ngrok monitor is running"
        MONITOR_PID=$(pgrep -f "monitor_ngrok.sh")
        echo "    PID: $MONITOR_PID"
    else
        echo -e "  ${RED}✗${NC} ngrok monitor is NOT running"
    fi
    
    # Check Flask health
    if curl -s http://localhost:5000/health > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Flask health check passed"
    else
        echo -e "  ${RED}✗${NC} Flask health check failed"
    fi
}

start_bot() {
    echo -e "${BLUE}Starting bot services...${NC}"
    ./start_bot.sh
}

stop_services() {
    echo -e "${YELLOW}Stopping all services...${NC}"
    pkill -f "python.*server.py" 2>/dev/null && echo -e "  ${GREEN}✓${NC} Flask server stopped"
    pkill -f "monitor_ngrok" 2>/dev/null && echo -e "  ${GREEN}✓${NC} ngrok monitor stopped"
    pkill -f "ngrok http" 2>/dev/null && echo -e "  ${GREEN}✓${NC} ngrok tunnel stopped"
    sleep 1
    echo -e "${GREEN}All services stopped${NC}"
}

restart_bot() {
    echo -e "${YELLOW}Restarting bot...${NC}"
    stop_services
    sleep 2
    start_bot
}

view_flask_logs() {
    echo -e "${BLUE}Flask Server Logs (Press Ctrl+C to exit):${NC}"
    echo ""
    tail -f /tmp/flask_server.log
}

view_ngrok_logs() {
    echo -e "${BLUE}ngrok Monitor Logs (Press Ctrl+C to exit):${NC}"
    echo ""
    tail -f /tmp/ngrok_monitor.log
}

restart_ngrok_manual() {
    echo -e "${YELLOW}Manually restarting ngrok...${NC}"
    pkill -f "ngrok http" 2>/dev/null
    sleep 2
    pkill -f "monitor_ngrok" 2>/dev/null
    sleep 2
    nohup ./monitor_ngrok.sh > /tmp/ngrok_monitor.log 2>&1 &
    echo -e "${GREEN}✓${NC} ngrok monitor restarted"
    sleep 3
    if pgrep -f "ngrok http" > /dev/null; then
        URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"[^"]*' | head -1 | cut -d'"' -f4)
        echo -e "${GREEN}✓${NC} ngrok tunnel active"
        if [ -n "$URL" ]; then
            echo -e "  URL: $URL"
        fi
    else
        echo -e "${RED}✗${NC} Failed to start ngrok"
    fi
}

# Main loop
while true; do
    print_menu
    read -p "Choose an option (1-8): " choice
    
    case $choice in
        1) start_bot ;;
        2) stop_services ;;
        3) restart_bot ;;
        4) view_flask_logs ;;
        5) view_ngrok_logs ;;
        6) check_status ;;
        7) restart_ngrok_manual ;;
        8) echo -e "${GREEN}Goodbye!${NC}"; exit 0 ;;
        *) echo -e "${RED}Invalid option${NC}" ;;
    esac
done
