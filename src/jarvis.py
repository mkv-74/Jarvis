"""
JARVIS - Just A Rather Very Intelligent System
Main backend process. Runs as a daemon, communicates with the UI via WebSocket.
"""

import asyncio
import json
import time
import threading
import numpy as np
import sounddevice as sd
import websockets
import logging
import subprocess
import os
import sys
from queue import Queue, Empty
from collections import deque
from pathlib import Path
from datetime import datetime

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("jarvis")

# ── Config ─────────────────────────────────────────────────────────────────────
CONFIG = {
    "ws_port": 8765,
    "sample_rate": 16000,
    "clap_threshold": 0.35,        # RMS energy threshold for clap
    "clap_window_ms": 500,         # Max ms between two claps for double-clap
    "clap_cooldown_s": 1.5,        # Seconds to ignore claps after trigger
    "vad_silence_ms": 1200,        # Ms of silence before ending speech
    "whisper_model": "base",       # tiny / base / small / medium / large-v3
    "ollama_model": "llama3.2",    # ollama model name
    "ollama_url": "http://localhost:11434/api/chat",
    "piper_model": "/usr/share/piper/en_US-lessac-high.onnx",
    "system_prompt": (
        "You are JARVIS, an intelligent AI assistant running locally on this machine. "
        "You are helpful, precise, and slightly witty — in the style of the AI from Iron Man. "
        "Always address the user as 'Sir' or 'Ma'am'. "
        "Keep responses concise — no more than 3 sentences unless more detail is specifically asked for. "
        "You have access to the user's computer and can open applications, search the web, "
        "and manage files when asked."
    ),
}

# ── Global state ───────────────────────────────────────────────────────────────
state = {
    "status": "idle",          # idle | listening | thinking | speaking
    "transcript": "",
    "response": "",
    "clap_detected": False,
    "history": [],
    "connected_clients": set(),
}

audio_queue: Queue = Queue()
speech_queue: Queue = Queue()


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket server — bridges Python backend ↔ Tauri UI
# ══════════════════════════════════════════════════════════════════════════════

async def ws_handler(websocket):
    state["connected_clients"].add(websocket)
    log.info(f"UI connected. Total clients: {len(state['connected_clients'])}")
    try:
        # Send current state on connect
        await websocket.send(json.dumps({"type": "state", "data": get_ui_state()}))
        async for message in websocket:
            await handle_ui_message(websocket, json.loads(message))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        state["connected_clients"].discard(websocket)


async def handle_ui_message(ws, msg):
    """Handle messages from the UI."""
    kind = msg.get("type")
    if kind == "toggle_listen":
        if state["status"] == "idle":
            await set_status("listening")
            speech_queue.put("manual_trigger")
        elif state["status"] == "listening":
            await set_status("idle")
    elif kind == "send_text":
        text = msg.get("text", "").strip()
        if text:
            asyncio.create_task(process_input(text))
    elif kind == "clear_history":
        state["history"] = []
        await broadcast({"type": "history_cleared"})


async def broadcast(data: dict):
    """Send a message to all connected UI clients."""
    if not state["connected_clients"]:
        return
    msg = json.dumps(data)
    dead = set()
    for ws in state["connected_clients"]:
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    state["connected_clients"] -= dead


async def set_status(new_status: str):
    state["status"] = new_status
    await broadcast({"type": "status", "status": new_status})
    log.info(f"Status → {new_status}")


def get_ui_state():
    return {
        "status": state["status"],
        "history": state["history"][-20:],  # Last 20 messages
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Clap Detection — runs in a background thread
# ══════════════════════════════════════════════════════════════════════════════

class ClapDetector:
    def __init__(self, on_double_clap):
        self.on_double_clap = on_double_clap
        self.clap_times = deque(maxlen=5)
        self.last_trigger = 0
        self.chunk_size = int(CONFIG["sample_rate"] * 0.05)  # 50ms chunks
        self.running = False

    def _rms(self, audio: np.ndarray) -> float:
        return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) / 32768.0

    def start(self):
        self.running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()
        log.info("Clap detector started")

    def stop(self):
        self.running = False

    def _listen_loop(self):
        with sd.InputStream(
            samplerate=CONFIG["sample_rate"],
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
        ) as stream:
            while self.running:
                chunk, _ = stream.read(self.chunk_size)
                rms = self._rms(chunk[:, 0])

                if rms > CONFIG["clap_threshold"]:
                    now = time.time()
                    # Debounce — ignore if same clap is still ringing
                    if not self.clap_times or (now - self.clap_times[-1]) > 0.1:
                        self.clap_times.append(now)
                        log.debug(f"Clap detected (RMS={rms:.3f})")

                        # Check for double clap within window
                        if len(self.clap_times) >= 2:
                            gap = self.clap_times[-1] - self.clap_times[-2]
                            cooldown_ok = (now - self.last_trigger) > CONFIG["clap_cooldown_s"]
                            if gap < (CONFIG["clap_window_ms"] / 1000) and cooldown_ok:
                                self.last_trigger = now
                                log.info("🫳🫳 Double clap detected!")
                                self.on_double_clap()


# ══════════════════════════════════════════════════════════════════════════════
#  Voice Activity Detection — simple energy-based VAD
# ══════════════════════════════════════════════════════════════════════════════

class VADRecorder:
    def __init__(self, on_speech_end):
        self.on_speech_end = on_speech_end
        self.running = False
        self.recording = False

    def start_recording(self):
        """Start listening for speech, call on_speech_end with audio when done."""
        threading.Thread(target=self._record_loop, daemon=True).start()

    def _record_loop(self):
        log.info("VAD: listening for speech...")
        sample_rate = CONFIG["sample_rate"]
        chunk_size = int(sample_rate * 0.1)  # 100ms chunks
        silence_chunks = int(CONFIG["vad_silence_ms"] / 100)
        speech_threshold = 0.01

        audio_buffer = []
        silence_count = 0
        speech_started = False

        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=chunk_size,
        ) as stream:
            for _ in range(100):  # Max 10 seconds
                chunk, _ = stream.read(chunk_size)
                audio_buffer.extend(chunk[:, 0].tolist())
                rms = float(np.sqrt(np.mean(chunk ** 2)))

                if rms > speech_threshold:
                    speech_started = True
                    silence_count = 0
                elif speech_started:
                    silence_count += 1
                    if silence_count >= silence_chunks:
                        break

        if speech_started and len(audio_buffer) > sample_rate * 0.3:
            audio = np.array(audio_buffer, dtype=np.float32)
            log.info(f"VAD: captured {len(audio)/sample_rate:.1f}s of speech")
            self.on_speech_end(audio)
        else:
            log.info("VAD: no speech detected")
            # Post idle status via asyncio
            asyncio.run_coroutine_threadsafe(set_status("idle"), loop)


# ══════════════════════════════════════════════════════════════════════════════
#  Speech-to-Text — faster-whisper with CUDA
# ══════════════════════════════════════════════════════════════════════════════

_whisper_model = None

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        log.info(f"Loading Whisper model: {CONFIG['whisper_model']}")
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(
            CONFIG["whisper_model"],
            device="cuda",
            compute_type="float16",
        )
        log.info("Whisper loaded ✓")
    return _whisper_model


def transcribe(audio: np.ndarray) -> str:
    model = get_whisper()
    segments, _ = model.transcribe(audio, beam_size=5, language="en")
    text = " ".join(seg.text.strip() for seg in segments).strip()
    log.info(f"Transcribed: {text!r}")
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  LLM — Ollama (local) or Claude API fallback
# ══════════════════════════════════════════════════════════════════════════════

def query_llm(user_text: str) -> str:
    import urllib.request

    messages = [{"role": "system", "content": CONFIG["system_prompt"]}]
    for turn in state["history"][-10:]:  # Last 10 turns for context
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_text})

    payload = json.dumps({
        "model": CONFIG["ollama_model"],
        "messages": messages,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        CONFIG["ollama_url"],
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["message"]["content"].strip()
    except Exception as e:
        log.error(f"LLM error: {e}")
        return "I'm sorry, Sir. I'm having trouble reaching the language model. Please ensure Ollama is running."


# ══════════════════════════════════════════════════════════════════════════════
#  Text-to-Speech — Piper TTS
# ══════════════════════════════════════════════════════════════════════════════

def speak(text: str):
    """Convert text to speech using Piper and play it."""
    log.info(f"Speaking: {text!r}")
    try:
        piper_model = CONFIG["piper_model"]
        if not Path(piper_model).exists():
            # Fallback to espeak if piper model not found
            subprocess.run(["espeak-ng", "-v", "en", "-s", "160", text],
                           capture_output=True)
            return

        proc = subprocess.Popen(
            ["piper", "--model", piper_model, "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        raw_audio, _ = proc.communicate(input=text.encode())

        # Play raw 16-bit PCM at 22050 Hz (Piper default)
        audio = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, samplerate=22050, blocking=True)

    except FileNotFoundError:
        log.warning("Piper not found, falling back to espeak-ng")
        subprocess.run(["espeak-ng", "-v", "en", "-s", "150", text],
                       capture_output=True)
    except Exception as e:
        log.error(f"TTS error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Computer Control — system actions JARVIS can take
# ══════════════════════════════════════════════════════════════════════════════

KNOWN_APPS = {
    "firefox": "firefox",
    "browser": "firefox",
    "chrome": "chromium",
    "terminal": "alacritty",
    "files": "nautilus",
    "file manager": "nautilus",
    "spotify": "spotify",
    "code": "code",
    "vscode": "code",
    "discord": "discord",
    "steam": "steam",
}

def handle_computer_action(text: str) -> str | None:
    """Check if the text contains a computer control command and execute it."""
    lower = text.lower()

    # Open app
    if any(kw in lower for kw in ["open ", "launch ", "start "]):
        for app_name, app_cmd in KNOWN_APPS.items():
            if app_name in lower:
                subprocess.Popen([app_cmd], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Opening {app_name.title()}, Sir."

    # Volume control
    if "volume up" in lower or "turn up" in lower:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"])
        return "Volume increased, Sir."
    if "volume down" in lower or "turn down" in lower:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"])
        return "Volume decreased, Sir."
    if "mute" in lower:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        return "Audio toggled, Sir."

    # Screenshot
    if "screenshot" in lower:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.home() / f"jarvis_screenshot_{ts}.png"
        subprocess.run(["scrot", str(path)])
        return f"Screenshot saved to your home folder, Sir."

    return None  # Not a computer action — let the LLM handle it


# ══════════════════════════════════════════════════════════════════════════════
#  Core pipeline — input → response → speak
# ══════════════════════════════════════════════════════════════════════════════

async def process_input(text: str):
    """Full pipeline: text in → LLM → speak → update UI."""
    if not text:
        await set_status("idle")
        return

    state["transcript"] = text
    await broadcast({"type": "transcript", "text": text})

    # Add to history
    state["history"].append({"role": "user", "content": text, "time": time.time()})
    await broadcast({"type": "history_update", "history": state["history"][-20:]})

    # Check for computer action first
    await set_status("thinking")
    action_response = handle_computer_action(text)

    if action_response:
        response = action_response
    else:
        # Query LLM in thread to avoid blocking the event loop
        response = await asyncio.get_event_loop().run_in_executor(
            None, query_llm, text
        )

    state["response"] = response
    state["history"].append({"role": "assistant", "content": response, "time": time.time()})
    await broadcast({
        "type": "response",
        "text": response,
        "history": state["history"][-20:],
    })

    # Speak in thread
    await set_status("speaking")
    await asyncio.get_event_loop().run_in_executor(None, speak, response)
    await set_status("idle")


def on_speech_captured(audio: np.ndarray):
    """Called from VAD thread when speech is captured."""
    asyncio.run_coroutine_threadsafe(set_status("thinking"), loop)
    text = transcribe(audio)
    if text:
        asyncio.run_coroutine_threadsafe(process_input(text), loop)
    else:
        asyncio.run_coroutine_threadsafe(set_status("idle"), loop)


def on_double_clap():
    """Called from clap detector thread."""
    if state["status"] != "idle":
        log.info("Double clap ignored — not idle")
        return

    async def _trigger():
        await set_status("listening")
        await broadcast({"type": "clap_detected"})
        vad = VADRecorder(on_speech_captured)
        vad.start_recording()

    asyncio.run_coroutine_threadsafe(_trigger(), loop)


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

loop = None

async def main():
    global loop
    loop = asyncio.get_event_loop()

    log.info("═" * 60)
    log.info("  JARVIS — Just A Rather Very Intelligent System")
    log.info("  Running on Arch Linux | CUDA | Ollama")
    log.info("═" * 60)

    # Pre-load Whisper in background
    threading.Thread(target=get_whisper, daemon=True).start()

    # Start clap detector
    clap = ClapDetector(on_double_clap)
    clap.start()

    # Start WebSocket server for UI
    log.info(f"WebSocket server starting on ws://localhost:{CONFIG['ws_port']}")
    async with websockets.serve(ws_handler, "localhost", CONFIG["ws_port"]):
        log.info("JARVIS is ready. Double-clap to activate.")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
