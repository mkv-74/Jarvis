#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  JARVIS Installer — Arch Linux (Omarchy) + AMD Ryzen + RTX 3050
#  Run with: bash install.sh
# ═══════════════════════════════════════════════════════════════
set -e

JARVIS_DIR="$HOME/.jarvis"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[JARVIS]${NC} $1"; }
success() { echo -e "${GREEN}[  OK  ]${NC} $1"; }
warn()    { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
error()   { echo -e "${RED}[ ERR  ]${NC} $1"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}━━ $1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

echo -e "${CYAN}"
cat << 'EOF'
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
  Just A Rather Very Intelligent System
  Arch Linux Installer
EOF
echo -e "${NC}"

# ── 1. System packages ────────────────────────────────────────────────────────
step "System packages"
info "Installing system dependencies via pacman..."
sudo pacman -Syu --noconfirm --needed \
    base-devel git curl wget \
    python python-pip python-virtualenv \
    portaudio \
    espeak-ng \
    scrot \
    webkit2gtk-4.1 \
    gtk3 \
    libappindicator-gtk3 \
    librsvg \
    patchelf

success "System packages installed"

# ── 2. CUDA / NVIDIA driver check ─────────────────────────────────────────────
step "CUDA check"
if command -v nvidia-smi &>/dev/null; then
    DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
    success "NVIDIA driver found: $DRIVER"
else
    warn "nvidia-smi not found. Installing NVIDIA packages..."
    sudo pacman -S --noconfirm --needed nvidia nvidia-utils cuda cudnn
fi

if ! python3 -c "import ctypes; ctypes.CDLL('libcuda.so.1')" 2>/dev/null; then
    warn "CUDA runtime not detected — ensure your NVIDIA drivers are loaded."
    warn "Run: sudo modprobe nvidia && reboot if needed."
fi
success "CUDA environment ready"

# ── 3. Rust (for Tauri) ───────────────────────────────────────────────────────
step "Rust toolchain"
if ! command -v rustc &>/dev/null; then
    info "Installing Rust via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
    source "$HOME/.cargo/env"
else
    success "Rust already installed: $(rustc --version)"
fi

# ── 4. Node.js (for Tauri CLI) ────────────────────────────────────────────────
step "Node.js"
if ! command -v node &>/dev/null; then
    info "Installing Node.js..."
    sudo pacman -S --noconfirm --needed nodejs npm
fi
success "Node.js: $(node --version)"

# ── 5. Python virtual environment + dependencies ──────────────────────────────
step "Python environment"
info "Creating virtual environment at $JARVIS_DIR/venv ..."
mkdir -p "$JARVIS_DIR"
python3 -m venv "$JARVIS_DIR/venv"
source "$JARVIS_DIR/venv/bin/activate"

info "Installing Python dependencies..."
pip install --upgrade pip wheel

# faster-whisper with CUDA support
pip install faster-whisper

# Audio
pip install sounddevice numpy scipy

# WebSocket
pip install websockets

info "Copying JARVIS source..."
cp -r "$SCRIPT_DIR/src/"* "$JARVIS_DIR/"

success "Python environment ready"
deactivate

# ── 6. Ollama ─────────────────────────────────────────────────────────────────
step "Ollama (local LLM)"
if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    success "Ollama already installed: $(ollama --version 2>/dev/null || echo 'installed')"
fi

info "Pulling Llama 3.2 model (this may take a few minutes)..."
ollama pull llama3.2 || warn "Could not pull llama3.2. Start ollama and run: ollama pull llama3.2"

success "Ollama ready"

# ── 7. Piper TTS ──────────────────────────────────────────────────────────────
step "Piper TTS"
if ! command -v piper &>/dev/null; then
    info "Installing Piper from AUR..."
    if command -v yay &>/dev/null; then
        yay -S --noconfirm piper-tts
    elif command -v paru &>/dev/null; then
        paru -S --noconfirm piper-tts
    else
        warn "No AUR helper found. Installing Piper manually..."
        PIPER_VERSION="2023.11.14-2"
        PIPER_URL="https://github.com/rhasspy/piper/releases/download/$PIPER_VERSION/piper_linux_x86_64.tar.gz"
        wget -O /tmp/piper.tar.gz "$PIPER_URL"
        tar -xzf /tmp/piper.tar.gz -C /tmp/
        sudo cp /tmp/piper/piper /usr/local/bin/
        sudo chmod +x /usr/local/bin/piper
    fi
fi

# Download voice model
PIPER_MODEL_DIR="/usr/share/piper"
sudo mkdir -p "$PIPER_MODEL_DIR"
VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx"
VOICE_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx.json"

if [ ! -f "$PIPER_MODEL_DIR/en_US-lessac-high.onnx" ]; then
    info "Downloading Piper voice model..."
    sudo wget -q --show-progress -O "$PIPER_MODEL_DIR/en_US-lessac-high.onnx" "$VOICE_URL"
    sudo wget -q -O "$PIPER_MODEL_DIR/en_US-lessac-high.onnx.json" "$VOICE_JSON_URL"
fi
success "Piper TTS ready"

# ── 8. Tauri desktop app ──────────────────────────────────────────────────────
step "Building JARVIS desktop app"
cd "$SCRIPT_DIR/ui"
info "Installing Node dependencies..."
npm install

info "Building Tauri app (this takes a few minutes on first build)..."
npm run build

# Copy the built app
TAURI_BUNDLE=$(find "$SCRIPT_DIR/ui/src-tauri/target/release/bundle" -name "jarvis" -type f 2>/dev/null | head -1)
if [ -n "$TAURI_BUNDLE" ]; then
    sudo cp "$TAURI_BUNDLE" /usr/local/bin/jarvis-ui
    success "Desktop app installed to /usr/local/bin/jarvis-ui"
else
    warn "Built binary not found — check ui/src-tauri/target/release/"
fi

# ── 9. systemd service for backend ───────────────────────────────────────────
step "Systemd service"
SERVICE_FILE="$HOME/.config/systemd/user/jarvis.service"
mkdir -p "$(dirname $SERVICE_FILE)"

cat > "$SERVICE_FILE" << SEOF
[Unit]
Description=JARVIS AI Backend
After=network.target

[Service]
Type=simple
ExecStart=$JARVIS_DIR/venv/bin/python $JARVIS_DIR/jarvis.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
SEOF

systemctl --user daemon-reload
systemctl --user enable jarvis
success "systemd service installed"

# ── 10. Desktop launcher ──────────────────────────────────────────────────────
step "Desktop launcher"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/jarvis.desktop" << DEOF
[Desktop Entry]
Name=JARVIS
Comment=Just A Rather Very Intelligent System
Exec=/usr/local/bin/jarvis-ui
Icon=utilities-terminal
Type=Application
Categories=Utility;Accessibility;
StartupNotify=true
DEOF
success "Desktop launcher created"

# ── Done ──────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}"
cat << 'EOF'
 ╔══════════════════════════════════════════════════╗
 ║   JARVIS installation complete.                  ║
 ║                                                  ║
 ║   Start backend:  systemctl --user start jarvis  ║
 ║   Launch UI:      jarvis-ui                      ║
 ║                                                  ║
 ║   Or run both:    bash start.sh                  ║
 ╚══════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
