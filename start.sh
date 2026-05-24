#!/usr/bin/env bash
# Start JARVIS backend + UI together
set -e

JARVIS_DIR="$HOME/.jarvis"
CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}Starting JARVIS...${NC}"

# Start Ollama if not running
if ! pgrep -x ollama > /dev/null; then
    echo "Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 2
fi

# Start Python backend
source "$JARVIS_DIR/venv/bin/activate"
python "$JARVIS_DIR/jarvis.py" &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID)"
sleep 1

# Launch UI
if command -v jarvis-ui &>/dev/null; then
    jarvis-ui &
elif [ -f "./ui/src-tauri/target/release/jarvis" ]; then
    ./ui/src-tauri/target/release/jarvis &
else
    echo "UI binary not found — run install.sh first"
fi

echo -e "${CYAN}JARVIS is running. Close the window to stop.${NC}"

# Wait for backend
wait $BACKEND_PID
