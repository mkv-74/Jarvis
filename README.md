<div align="center">

```
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
```

**Just A Rather Very Intelligent System**

*Local AI assistant for Arch Linux — double-clap to activate*

![Platform](https://img.shields.io/badge/platform-Arch%20Linux-1793d1?style=flat-square&logo=arch-linux)
![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76b900?style=flat-square&logo=nvidia)
![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

</div>

---

## Features

- 👏 **Double-clap activation** — just like Iron Man 2
- 🎙 **Voice recognition** — Whisper running locally on your GPU
- 🧠 **Local AI brain** — Llama 3.2 via Ollama, fully offline
- 🔊 **Voice responses** — Piper TTS with a natural voice
- 🖥 **Computer control** — open apps, volume, screenshots
- 🤖 **HUD desktop UI** — arc reactor aesthetic built with Tauri

## Quick Install

```bash
git clone https://github.com/mkv-74/jarvis.git
cd jarvis
bash install.sh
```

Then:

```bash
bash start.sh
```

See [INSTALL.md](INSTALL.md) for the full guide, troubleshooting, and configuration options.

## Requirements

- Arch Linux (or Omarchy / any Arch flavour)
- NVIDIA GPU with CUDA support
- Microphone
- 8GB+ RAM, 6GB+ VRAM recommended

## Stack

| Component | Tool |
|-----------|------|
| Speech-to-text | faster-whisper (CUDA) |
| LLM | Ollama + Llama 3.2 |
| Text-to-speech | Piper TTS |
| Desktop app | Tauri v2 |
| Audio | sounddevice + portaudio |

## License

MIT
