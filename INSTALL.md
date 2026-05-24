# JARVIS — Installation Guide
### Arch Linux (Omarchy) · AMD Ryzen 5 5500 · RTX 3050 6GB

---

## What you're building

JARVIS is a local AI assistant that lives on your desktop. It has:

- **Double-clap activation** — clap twice and it starts listening
- **Voice recognition** — Whisper running on your RTX 3050 via CUDA
- **AI brain** — Llama 3.2 running locally via Ollama (no internet needed)
- **Voice responses** — Piper TTS, sounds natural
- **Computer control** — open apps, control volume, take screenshots
- **HUD-style desktop UI** — Iron Man arc reactor aesthetic

Everything runs offline on your machine. Nothing gets sent to the cloud unless you explicitly switch the model to Claude API.

---

## Before you start — things to check

Open a terminal and verify these:

```bash
# Make sure your NVIDIA driver is loaded
nvidia-smi
# Should show your RTX 3050 with driver version

# Check your microphone is detected
arecord -l
# Should list at least one capture device

# Check your audio output works
aplay /usr/share/sounds/alsa/Front_Left.wav
```

If `nvidia-smi` fails, install your GPU driver first:
```bash
sudo pacman -S nvidia nvidia-utils
sudo reboot
```

---

## Step 1 — Download JARVIS

```bash
# Clone the repo
git clone https://github.com/yourusername/jarvis.git
cd jarvis

# Make scripts executable
chmod +x install.sh start.sh
```

---

## Step 2 — Run the installer

```bash
bash install.sh
```

The installer will walk through each step automatically. Here's what it does so you know what to expect:

| Step | What happens | Time |
|------|-------------|------|
| System packages | installs portaudio, espeak, scrot etc | ~1 min |
| CUDA check | verifies your GPU is visible | instant |
| Rust | installs rustup + stable toolchain | ~3 min |
| Node.js | installs for Tauri CLI | ~1 min |
| Python venv | creates isolated environment, installs deps | ~2 min |
| Ollama | installs the local LLM runner | ~1 min |
| Llama 3.2 model | **downloads ~2GB model** | 5–15 min |
| Piper TTS | installs + downloads voice model (~60MB) | ~2 min |
| Tauri build | compiles the desktop app | ~5 min first time |
| systemd service | registers JARVIS as a background service | instant |

**Total: roughly 20–30 minutes**, mostly waiting for downloads.

---

## Step 3 — Start JARVIS

```bash
bash start.sh
```

This starts the Python backend (which listens for claps and handles voice) and launches the desktop UI window.

To start automatically on login:
```bash
systemctl --user enable --now jarvis
```

Then launch just the UI separately:
```bash
jarvis-ui
```

---

## How to use it

### Clap activation (Iron Man style)
Double-clap anywhere — two claps within ~500ms. The arc reactor in the UI will flash and it starts listening. Speak your command, pause, and JARVIS responds.

### Click to talk
Click the arc reactor button in the UI, or the microphone button below the conversation.

### Type a command
Type anything in the input box and hit Enter or Send.

### Voice commands that work out of the box

| You say | What happens |
|---------|-------------|
| "Open Firefox" | Launches Firefox |
| "Open terminal" | Opens Alacritty |
| "Volume up / down" | Adjusts system volume |
| "Mute" | Toggles audio |
| "Take a screenshot" | Saves to your home folder |
| Anything else | Sent to Llama 3.2 for a response |

---

## Changing the AI model

Open `~/.jarvis/jarvis.py` and find the `CONFIG` block near the top:

```python
CONFIG = {
    "ollama_model": "llama3.2",   # change this
    ...
}
```

To use a different model, first pull it:
```bash
ollama pull mistral        # fast, good at instructions
ollama pull llama3.2       # default, well-rounded
ollama pull phi3:medium    # smaller, uses less VRAM
```

Then change `ollama_model` to match and restart:
```bash
systemctl --user restart jarvis
```

### Using Claude API instead (better quality, needs internet)

In `~/.jarvis/jarvis.py`, replace the `query_llm` function with:

```python
def query_llm(user_text: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key="YOUR_API_KEY_HERE")
    messages = state["history"][-10:]
    messages.append({"role": "user", "content": user_text})
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=CONFIG["system_prompt"],
        messages=messages,
    )
    return response.content[0].text
```

Install the SDK: `pip install anthropic` in your venv.

---

## Tuning clap sensitivity

If JARVIS triggers too easily (loud keyboard, music) or not enough:

Open `~/.jarvis/jarvis.py`, find `CONFIG`, adjust:

```python
"clap_threshold": 0.35,   # raise this if too sensitive (try 0.5–0.7)
                           # lower this if it misses claps (try 0.2–0.3)
"clap_window_ms": 500,    # ms between the two claps (default 500ms is good)
```

Restart after changing: `systemctl --user restart jarvis`

---

## Troubleshooting

**JARVIS doesn't hear my claps**
Run this to see live RMS levels and calibrate:
```bash
python3 -c "
import sounddevice as sd, numpy as np, time
with sd.InputStream(samplerate=16000, channels=1, dtype='int16') as s:
    while True:
        c, _ = s.read(800)
        rms = np.sqrt(np.mean(c.astype(float)**2)) / 32768
        print(f'RMS: {rms:.3f}', '█' * int(rms * 200))
        time.sleep(0.05)
"
```
Clap and watch the value — set `clap_threshold` to about 80% of what you see.

**Whisper is slow / crashes**
Your 6GB VRAM fits `base` or `small` models fine. If it crashes try:
```python
"whisper_model": "tiny",  # fastest, least accurate
```

**Ollama not responding**
```bash
systemctl status ollama    # check if running
ollama serve               # start manually
ollama list                # confirm model is downloaded
```

**No sound output**
```bash
pactl list sinks           # list audio outputs
pactl set-default-sink <name>   # set your preferred output
```

**UI won't open / white screen**
The backend must be running first. Check:
```bash
systemctl --user status jarvis
# or run manually:
source ~/.jarvis/venv/bin/activate
python ~/.jarvis/jarvis.py
```

---

## File layout

```
~/.jarvis/
├── jarvis.py          ← main backend (edit config here)
├── venv/              ← Python virtual environment
└── ...

~/jarvis/              ← source repo
├── src/
│   └── jarvis.py      ← backend source
├── ui/
│   ├── src/
│   │   └── index.html ← UI (edit appearance here)
│   └── src-tauri/     ← Tauri desktop wrapper
├── install.sh
└── start.sh
```

---

## Upgrading

```bash
cd ~/jarvis
git pull
bash install.sh         # re-runs safely, skips already-installed steps
systemctl --user restart jarvis
```

---

## Uninstalling

```bash
systemctl --user disable --now jarvis
rm -rf ~/.jarvis
rm ~/.config/systemd/user/jarvis.service
rm ~/.local/share/applications/jarvis.desktop
sudo rm /usr/local/bin/jarvis-ui
```

---

*JARVIS v1.0 — Built for Omarchy / Arch Linux*
