#!/usr/bin/env python3
"""
config.py — Centralized configuration for Vovy.

Manages API endpoints, model selection, capture dimensions, and safety
settings. All configuration is data-driven via dataclasses so that
``main.py`` and ``vision_agent.py`` stay declarative.

Made by Viperwraith47 — https://github.com/viperwraith47
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


# ── .env file loader ──────────────────────────────────────────────

def _load_env(dotenv_path: str = ".env") -> None:
    """Load environment variables from a .env file (simple loader, no external deps)."""
    if not os.path.exists(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)
    except Exception:
        pass  # Silent fail — missing .env is fine


# Load .env at import time so all os.environ calls below pick up the values
_load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


# ── Available vision models ──────────────────────────────────────
# Each entry maps a model slug to its deployment endpoint and metadata.
# Users can toggle between these at runtime via the UI or env vars.
AVAILABLE_MODELS: dict[str, dict[str, Any]] = {
    "llama-3.2-vision": {
        "display_name": "Llama-3.2-Vision",
        "endpoint": os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434/v1/chat/completions"),
        "api_key": os.environ.get("OLLAMA_API_KEY", "ollama"),
        "max_tokens": 2048,
        "supports_tools": False,
        "description": "Ollama local Llama-3.2-Vision model",
    },
    "qwen2.5-vl": {
        "display_name": "Qwen2.5-VL",
        "endpoint": os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434/v1/chat/completions"),
        "api_key": os.environ.get("OLLAMA_API_KEY", "ollama"),
        "max_tokens": 2048,
        "supports_tools": False,
        "description": "Ollama local Qwen2.5-VL model",
    },
    "gemini-2.0-flash": {
        "display_name": "Gemini 2.0 Flash",
        "endpoint": os.environ.get("GOOGLE_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
        "api_key": os.environ.get("GOOGLE_API_KEY", ""),
        "max_tokens": 4096,
        "supports_tools": True,
        "description": "Google AI Studio Gemini 2.0 Flash (external gateway)",
    },
    "gpt-4o": {
        "display_name": "GPT-4o",
        "endpoint": os.environ.get("OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions"),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "max_tokens": 4096,
        "supports_tools": True,
        "description": "OpenAI GPT-4o (external gateway)",
    },
    "gpt-4-vision-preview": {
        "display_name": "GPT-4 Vision",
        "endpoint": os.environ.get("OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions"),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "max_tokens": 4096,
        "supports_tools": True,
        "description": "OpenAI GPT-4 Vision (external gateway)",
    },
}


@dataclass
class VisionConfig:
    """Configuration for the vision loop and API communication."""

    # Screen capture dimensions (fixed canvas as required)
    capture_width: int = 1024
    capture_height: int = 768

    # Default model slug (must exist in AVAILABLE_MODELS)
    default_model: str = field(
        default_factory=lambda: os.environ.get("VOVY_DEFAULT_MODEL", "llama-3.2-vision")
    )

    # Request parameters
    max_tokens: int = 2048
    temperature: float = 0.3
    top_p: float = 0.9

    # Loop timing (seconds between vision iterations)
    loop_interval: float = 2.0

    # System prompt — instructs the LLM to return structured JSON actions
    system_prompt: str = (
        "You are Vovy, a desktop automation agent with Apple Glass UI. "
        "You receive screen captures and return structured JSON actions to control the mouse, "
        "keyboard, and invoke system tools. "
        "Available tools: view_file, list_directory, execute_command, get_mouse_position, "
        "take_screenshot, move_cursor, click_at, scroll_at, type_text. "
        "Return ONLY valid JSON matching the schema: "
        '{"actions": [{"type": "move"|"click"|"scroll"|"type", ...}], '
        '"tool_calls": [{"name": "...", "arguments": {...}}], '
        '"reasoning": "..."} '
        "Normalized coordinates [0,1] map to the 1024x768 capture canvas. "
        "Do not include explanations outside the JSON."
    )

    # Prompt sent with each screenshot
    vision_prompt: str = (
        "Analyze this screen capture. If you see a task to complete, "
        "return JSON actions to accomplish it. If the desktop is idle, "
        "return an empty actions array. Always be helpful and safe."
    )

    def endpoint(self) -> str:
        """Return the API endpoint for the current default model."""
        return AVAILABLE_MODELS[self.default_model]["endpoint"]

    def api_key(self) -> str:
        """Return the API key for the current default model."""
        return AVAILABLE_MODELS[self.default_model]["api_key"]

    def display_name(self) -> str:
        """Return the human-readable model name."""
        return AVAILABLE_MODELS[self.default_model]["display_name"]

    def switch_model(self, model_slug: str) -> bool:
        """Toggle the default model. Returns True if successful."""
        if model_slug in AVAILABLE_MODELS:
            self.default_model = model_slug
            return True
        return False

    def list_models(self) -> list[str]:
        """Return list of available model slugs."""
        return list(AVAILABLE_MODELS.keys())


@dataclass
class SafetyConfig:
    """Safety thresholds and fail-safes for automation."""

    # Hardware fail-safe: moving mouse to this corner (in pixels) stops the loop.
    # Default: top-left corner (0, 0).
    fail_safe_corner: tuple[int, int] = (0, 0)

    # Pixel radius (in screen coordinates) around the fail-safe corner that
    # triggers termination.
    fail_safe_radius: int = 3

    # Whether to enable the fail-safe at all
    enable_fail_safe: bool = True

    # Bounds checking for normalized coordinates [0.0, 1.0]
    clamp_coordinates: bool = True

    # Maximum pyautogui move duration (seconds) — prevents runaway moves
    max_move_duration: float = 2.0

    # Maximum scroll amount per iteration
    max_scroll_delta: int = 100


@dataclass
class UIConfig:
    """Configuration for the Apple Glass UI."""

    # Window / orb dimensions
    orb_size: int = 48  # diameter in pixels
    orb_glow_radius: int = 24  # extra glow beyond the circle
    panel_width: int = 360
    panel_height: int = 280

    # Animation timings (seconds) — critically damped springs, no bounce
    spring_response: float = 0.35
    spring_damping: float = 1.0
    orb_follow_speed: float = 0.25  # lower = slower follow

    # Colors (Apple Glass palette)
    orb_color: tuple[float, float, float, float] = (0.4, 0.7, 1.0, 0.7)
    orb_glow_color: tuple[float, float, float, float] = (0.4, 0.7, 1.0, 0.3)
    panel_bg_color: tuple[float, float, float, float] = (0.1, 0.1, 0.12, 0.45)
    rim_gradient_start: float = 0.55  # white opacity at top-left
    rim_gradient_end: float = 0.05    # white opacity at bottom-right

    # Docking threshold — pixels from screen edge at which orb docks
    dock_threshold: int = 60

    # Status bar update interval (seconds)
    status_update_interval: float = 0.5


@dataclass
class AppConfig:
    """Top-level application configuration."""

    vision: VisionConfig = field(default_factory=VisionConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # App metadata
    app_name: str = "Vovy"
    version: str = "1.0.0"
    author: str = "Viperwraith47"
    author_url: str = "https://github.com/viperwraith47"

    # Log file path
    log_dir: str = field(
        default_factory=lambda: os.path.expanduser("~/.vovy/logs")
    )

    # State directory
    state_dir: str = field(
        default_factory=lambda: os.path.expanduser("~/.vovy")
    )

    def ensure_directories(self) -> None:
        """Create log and state directories if they don't exist."""
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.state_dir, exist_ok=True)

    def toggle_model(self, model_slug: str) -> str | None:
        """Switch the active vision model. Returns the display name or None."""
        if self.vision.switch_model(model_slug):
            return self.vision.display_name()
        return None
