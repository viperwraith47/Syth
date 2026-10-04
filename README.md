# Vovy

> A macOS desktop agent with an **Apple Glass** (absolute glassmorphism) user interface. Continuously captures the screen, sends screenshots to a local or external Vision API, parses LLM-returned JSON actions, and executes them via `pyautogui` with human-like easing — all orchestrated through a modular Python architecture with Google Stitch MCP tool routing.

**Made by [Viperwraith47](https://github.com/viperwraith47)**

[![macOS](https://img.shields.io/badge/macOS-14%2B-blue?logo=apple)](https://www.apple.com/macos/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://python.org)
[![PySide6](https://img.shields.io/badge/UI-PySide6-55%2B-blue?logo=qt)](https://www.pyside.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Made by Viperwraith47](https://img.shields.io/badge/Made%20by-Viperwraith47-blueviolet?logo=github)](https://github.com/viperwraith47)

---

## Features

- **Apple Glass UI** — absolute glassmorphism: completely transparent panel, native system background blur (vibrancy), subtle rim-light highlights, depth shadows, and a floating glowing orb anchor that follows the cursor or docks to screen edges
- **OS World Vision Loop** — infinite execution loop using Pillow to capture the 1024×768 screen canvas, compress and encode frames as base64 payloads
- **Physical Cursor Action Engine** — parses structured JSON actions from OpenAI-compatible Vision API models; uses `pyautogui` with human-like easing for mouse movement, left/right clicks, scrolling, and native string typing
- **Local AI Server Connection** — routes payloads to `http://localhost:11434/v1` (Ollama) or external OpenAI-compatible gateways; dynamic model toggling between Llama-3.2-Vision, Qwen2.5-VL, and GPT-4 families
- **Google Stitch MCP Integration** — exposes system functions as structured tools (view file, list directory, execute command, take screenshot, etc.) so the LLM can explicitly request filesystem and system operations
- **Resilient Automation Safety** — coordinate bounds checking, hardware fail-safe (mouse to top-left corner instantly terminates the loop), and error logging for missing macOS Accessibility & Screen Recording permissions
- **Viperwraith47 Apple Liquid Glass reference** — SwiftUI templates in `Sources/Vovy/LiquidGlass/` and `Sources/Vovy/Credits/` for the canonical Swift implementation

## Requirements

- macOS 14 Sonoma or later (Apple Glass vibrancy works best on recent macOS)
- Python 3.11+ (tested on Python 3.14)
- Apple Silicon or Intel Mac
- macOS permissions: **Screen Recording** and **Accessibility** (granted via System Settings → Privacy & Security)
- Optional: Ollama running locally (`http://localhost:11434`) or an external OpenAI-compatible API key

## Quick Start

```bash
chmod +x build.sh
./build.sh
```

Or run manually:

```bash
pip3 install -r requirements.txt
python3 main.py
```

## CLI Usage

```bash
# Launch with Apple Glass UI (default)
python3 main.py

# Run vision loop without UI (headless)
python3 main.py --headless

# Use a specific model
python3 main.py --model qwen2.5-vl

# Override API endpoint
python3 main.py --endpoint http://localhost:11434/v1/chat/completions

# Disable the top-left fail-safe (NOT RECOMMENDED)
python3 main.py --no-fail-safe

# List available models
python3 main.py --list-models

# Verbose/debug logging
python3 main.py --verbose
```

## AI Models & API Keys

Vovy supports multiple vision-capable AI backends. Configure API keys in a
local `.env` file (automatically loaded at startup, gitignored):

```dotenv
# Google AI Studio (Gemini)
GOOGLE_API_KEY=your_gemini_api_key_here

# OpenAI-compatible gateway
OPENAI_API_KEY=your_openai_key_here

# Ollama local (optional override)
OLLAMA_ENDPOINT=http://localhost:11434/v1/chat/completions
OLLAMA_API_KEY=ollama
```

| Model | Backend | Key Required |
|---|---|---|
| `llama-3.2-vision` | Ollama (local) | No (default: `ollama`) |
| `qwen2.5-vl` | Ollama (local) | No (default: `ollama`) |
| `gemini-2.0-flash` | Google AI Studio | Yes — `GOOGLE_API_KEY` |
| `gpt-4o` | OpenAI | Yes — `OPENAI_API_KEY` |
| `gpt-4-vision-preview` | OpenAI | Yes — `OPENAI_API_KEY` |

## Project Structure

```
.
├── build.sh                          # R1 — Build script with Viperwraith47 banner
├── README.md                         # R2 — This file
├── AGENTS.md                         # Short agent rules (pointer to contract)
├── PROJECT_REQUIREMENTS.md           # Full Viperwraith47 project constitution
├── macos-app-project-initializer.md  # Same contract (alternate name)
├── requirements.txt                  # Python dependencies
├── LICENSE                           # MIT
├── main.py                           # App entrypoint & UI orchestration
├── vision_agent.py                   # OS World Vision Loop + Cursor Action Engine
├── mcp_tools.py                      # Google Stitch MCP tool definitions
├── glass_ui.py                       # Apple Glass UI (PySide6 + tkinter fallback)
├── config.py                         # Centralized configuration
├── utils.py                          # Logging, permissions, coordinates, easing
└── Sources/
    └── Vovy/
        ├── LiquidGlass/              # R3 — Swift Liquid Glass reference
        │   ├── LiquidGlassBackground.swift
        │   └── GlassModifiers.swift
        └── Credits/                  # R4 — Swift Viperwraith47 credit reference
            └── ViperwraithCreditView.swift
```

## Architecture

### OS World Vision Loop (`vision_agent.py`)

1. **Capture** — Pillow (via `pyautogui.screenshot()`) captures the screen, resizes to 1024×768
2. **Encode** — Frame compressed as PNG, base64-encoded into a payload string
3. **Request** — Sends to OpenAI-compatible API (Ollama or external gateway) with tool schemas
4. **Parse** — LLM response parsed into action commands (`move`, `click`, `scroll`, `type`) and MCP tool calls
5. **Execute** — Actions dispatched via `pyautogui` with human-like easing; tool calls dispatched via `ToolRegistry`
6. **Loop** — Conversation history retained for multi-turn context; repeats every 2s

### Physical Cursor Action Engine

| Action | pyautogui Method | Notes |
|---|---|---|
| `move` | `pyautogui.moveTo()` | Human-like easing, normalized → screen coords |
| `click` | `pyautogui.click()` | Left/right/middle, optional target coords |
| `scroll` | `pyautogui.scroll()` | Continuous, horizontal support |
| `type` | `pyautogui.write()` | Native string typing with interval |
| `drag` | `mouseDown + moveTo + mouseUp` | Smooth drag gestures |

### MCP Tools (`mcp_tools.py`)

Following the Google Stitch Model Context Protocol (MCP), the following tools are exposed:

| Tool | Description |
|---|---|
| `view_file` | Read a file's contents |
| `list_directory` | List directory contents |
| `execute_command` | Execute a shell command |
| `get_mouse_position` | Get current cursor coordinates |
| `click_at` | Click at screen coordinates |
| `move_cursor` | Move cursor with easing |
| `scroll_at` | Scroll the mouse wheel |
| `type_text` | Type a string of text |
| `take_screenshot` | Capture a screen region as base64 |
| `read_screen_text` | Read text from screen (OCR via pytesseract if available) |

### Apple Glass UI (`glass_ui.py`)

- **Blurred background** — Screen capture behind the panel + Gaussian blur simulates macOS vibrancy
- **Rim light** — 1px white gradient border (55% → 5%) mimics Apple's specular highlight
- **Depth** — Layered shadows (`black 18% radius 24 y12` + `black 6% radius 2 y1`)
- **Floating orb** — Glowing radial gradient widget follows cursor; docks to screen edges
- **Vibrant backdrop** — Blue→purple gradient behind the glass panel so translucency is visible
- **Continuous corners** — `border-radius: 20-24px, style: .continuous` equivalent

### Safety & Fail-Safe

- **Coordinate bounds checking** — All normalized `[0,1]` coordinates clamped to screen bounds
- **Hardware fail-safe** — Mouse to top-left corner `(0, 0)` within 3px instantly terminates the vision loop
- **Permission logging** — Checks Accessibility & Screen Recording; logs remediation steps if missing

## Model Configuration

| Model | Endpoint | Type |
|---|---|---|
| `llama-3.2-vision` | `http://localhost:11434/v1/chat/completions` | Ollama (local) |
| `qwen2.5-vl` | `http://localhost:11434/v1/chat/completions` | Ollama (local) |
| `gpt-4o` | `https://api.openai.com/v1/chat/completions` | OpenAI (external) |
| `gpt-4-vision-preview` | `https://api.openai.com/v1/chat/completions` | OpenAI (external) |

Toggle models at runtime via the UI dropdown or `--model` CLI flag. Override endpoints with `--endpoint` or environment variables `OLLAMA_ENDPOINT` / `OPENAI_ENDPOINT`.

## Credits

Created and maintained by **[Viperwraith47](https://github.com/viperwraith47)**.

The in-app credit footer (visible in the Apple Glass UI) opens [https://github.com/viperwraith47](https://github.com/viperwraith47) in your default browser on click.

## License

MIT — use freely for personal and commercial projects. See [LICENSE](./LICENSE) for details.

---

*Made by [Viperwraith47](https://github.com/viperwraith47) — Apple Glass UI, macOS automation, and Viperwraith47 Liquid Glass design system.*
