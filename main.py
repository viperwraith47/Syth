#!/usr/bin/env python3
"""
main.py — Vovy Application Entrypoint & UI Orchestration.

Vovy is a macOS desktop agent with an Apple Glass (glassmorphism) user
interface. It continuously captures the screen, sends screenshots to a
local or external OpenAI-compatible Vision API, parses the LLM's JSON
actions, and executes them via pyautogui with human-like easing.

The UI features:
  • Absolute glassmorphism — transparent panel with native blur
  • Subtle rim-light border highlights
  • A floating glowing orb that follows the mouse or docks to screen edges
  • Viperwraith47 credit footer (clickable → opens GitHub profile)

Architecture:
  main.py         ← This file (entrypoint, UI orchestration)
  vision_agent.py ← OS World Vision Loop + Cursor Action Engine
  mcp_tools.py    ← Google Stitch MCP tool definitions & execution
  glass_ui.py     ← Apple Glass UI (PySide6 + tkinter fallback)
  config.py       ← Centralized configuration
  utils.py        ← Logging, permissions, coordinates, easing

Made by Viperwraith47 — https://github.com/viperwraith47
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

# Ensure the project directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import AppConfig, AVAILABLE_MODELS
from utils import setup_logging, check_macos_permissions, get_screen_size, open_url
from mcp_tools import ToolRegistry
from vision_agent import VisionAgent, VisionConfig
from glass_ui import (
    PYSIDE6_AVAILABLE,
    AppleGlassWindow,
    TkGlassUI,
    sys_platform_darwin,
)


# ── Application Class ──────────────────────────────────────────────────────


class VovyApp:
    """
    Main application orchestrator.

    Coordinates:
      • Logging and configuration
      • macOS permission checks
      • MCP tool registry
      • Vision agent (background thread)
      • Apple Glass UI (PySide6 or tkinter fallback)
    """

    def __init__(self, args: argparse.Namespace | None = None):
        self.args = args or argparse.Namespace()

        # ── Configuration ────────────────────────────────────────
        self.config = AppConfig()

        # Override config from CLI args
        if hasattr(self.args, "model") and self.args.model:
            if self.args.model in AVAILABLE_MODELS:
                self.config.vision.default_model = self.args.model
            else:
                print(f"⚠ Unknown model '{self.args.model}' — using default: "
                      f"{self.config.vision.display_name()}")

        if hasattr(self.args, "endpoint") and self.args.endpoint:
            AVAILABLE_MODELS[self.config.vision.default_model]["endpoint"] = self.args.endpoint

        if hasattr(self.args, "verbose") and self.args.verbose:
            self._log_level = logging.DEBUG
        else:
            self._log_level = logging.INFO

        if hasattr(self.args, "loop_interval") and self.args.loop_interval:
            self.config.vision.loop_interval = self.args.loop_interval

        if hasattr(self.args, "no_fail_safe") and self.args.no_fail_safe:
            self.config.safety.enable_fail_safe = False

        # ── Ensure directories ───────────────────────────────────
        self.config.ensure_directories()

        # ── Logging ──────────────────────────────────────────────
        self.logger = setup_logging(self.config.log_dir, level=self._log_level)
        self.logger.info("=" * 60)
        self.logger.info(f"Vovy v{self.config.version}")
        self.logger.info(f"Made by Viperwraith47 — https://github.com/viperwraith47")
        self.logger.info(f"Platform: {sys.platform} | Python: {sys.version.split()[0]}")
        self.logger.info(f"UI backend: {glass_ui_backend_name()}")
        self.logger.info(f"Model: {self.config.vision.display_name()} | "
                         f"Endpoint: {self.config.vision.endpoint()}")
        self.logger.info(f"Screen: {get_screen_size()[0]}×{get_screen_size()[1]}")
        self.logger.info(f"Fail-safe: {'enabled' if self.config.safety.enable_fail_safe else 'disabled'} "
                        f"(top-left corner within {self.config.safety.fail_safe_radius}px)")
        self.logger.info("=" * 60)

        # ── Permission check ─────────────────────────────────────
        self._check_permissions()

        # ── MCP Tool Registry ────────────────────────────────────
        self.tool_registry = ToolRegistry(logger=self.logger)
        self.logger.info(f"Registered {len(self.tool_registry.list_tools())} MCP tools: "
                         f"{', '.join(self.tool_registry.list_tools())}")

        # ── Vision Agent ─────────────────────────────────────────
        self.vision_agent = VisionAgent(
            vision_config=self.config.vision,
            safety_config=self.config.safety,
            tool_registry=self.tool_registry,
            logger=self.logger,
        )

        # ── UI ───────────────────────────────────────────────────
        self._ui = None
        self._ui_app = None
        self._vision_thread: threading.Thread | None = None

        # Flag to prevent double-shutdown
        self._shutting_down = False

    def _check_permissions(self) -> None:
        """Check macOS permissions and log warnings."""
        if sys_platform_darwin():
            perms = check_macos_permissions(self.logger)
            missing = [k for k, v in perms.items() if not v]
            if missing:
                self.logger.error(
                    f"MISSING macOS PERMISSIONS: {', '.join(missing)}"
                )
                self.logger.error(
                    "Screen Recording permission is required for screen capture. "
                    "Accessibility permission is required for mouse/keyboard control."
                )
                self.logger.error(
                    "Open System Settings → Privacy & Security → "
                    "Screen Recording and Accessibility, and grant access to Terminal/Python."
                )
                # Don't exit — let the user try anyway (they might grant later)
        else:
            self.logger.info("Non-macOS platform detected — skipping permission checks.")

    def _start_vision_loop(self) -> None:
        """Start the vision loop in a background daemon thread."""
        if self._vision_thread is not None and self._vision_thread.is_alive():
            self.logger.warning("Vision loop is already running")
            return

        self._vision_thread = threading.Thread(
            target=self.vision_agent.run,
            daemon=True,
            name="Vovy-VisionLoop",
        )
        self._vision_thread.start()
        self.logger.info("Vision loop started in background thread")

    def _stop_vision_loop(self) -> None:
        """Signal the vision loop to stop."""
        if self.vision_agent.is_running:
            self.vision_agent.stop()
            self.logger.info("Vision loop stop signal sent")
        if self._vision_thread is not None:
            self._vision_thread.join(timeout=5.0)
            self.logger.info("Vision loop thread terminated")

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def handler(signum, frame):
            self.logger.info(f"Received signal {signum} — shutting down...")
            self.shutdown()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _build_ui(self):
        """Build and show the UI."""
        if PYSIDE6_AVAILABLE:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt

            self._ui_app = QApplication.instance() or QApplication(sys.argv)
            self._ui_app.setApplicationName(self.config.app_name)

            self._ui = AppleGlassWindow(
                app_config=self.config,
                vision_agent=self.vision_agent,
                tool_registry=self.tool_registry,
                logger=self.logger,
            )
            self._ui.show()

            self.logger.info("Apple Glass UI created (PySide6)")
            return self._ui_app
        else:
            # Tkinter fallback
            self._ui = TkGlassUI(
                app_config=self.config,
                vision_agent=self.vision_agent,
                tool_registry=self.tool_registry,
                logger=self.logger,
            )
            self._ui.show()
            self.logger.info("Tkinter fallback UI created (PySide6 not available)")
            # Tkinter doesn't have a separate app object
            import tkinter
            self._ui_app = tkinter  # placeholder
            return None

    def run(self) -> int:
        """
        Run the application.

        If --headless is specified, runs only the vision loop without UI.
        Otherwise, creates the Apple Glass UI and runs the event loop.
        """
        self._setup_signal_handlers()

        # Headless mode (no UI)
        if hasattr(self.args, "headless") and self.args.headless:
            self.logger.info("Running in headless mode (no UI)")
            self._start_vision_loop()

            try:
                while self.vision_agent.is_running:
                    self._vision_thread.join(timeout=1.0)
                    if not self._vision_thread.is_alive():
                        break
            except KeyboardInterrupt:
                pass

            self.shutdown()
            return 0

        # ── List models and exit ────────────────────────────────
        if hasattr(self.args, "list_models") and self.args.list_models:
            print("\nAvailable Vision Models:")
            print("-" * 55)
            for slug, info in AVAILABLE_MODELS.items():
                active = " ◄" if slug == self.config.vision.default_model else ""
                print(f"  {info['display_name']:<20} ({slug}){active}")
            print(f"\nEndpoint: {self.config.vision.endpoint()}")
            return 0

        # ── Full application with UI ────────────────────────────
        self._build_ui()

        # Start vision loop after UI is ready (gives the orb time to initialize)
        # Slight delay for the orb to position itself
        if PYSIDE6_AVAILABLE:
            from PySide6.QtCore import QTimer

            # Start vision loop shortly after UI launch
            QTimer.singleShot(500, self._start_vision_loop)

            # Run the Qt event loop
            exit_code = self._ui_app.exec()
            self.logger.info(f"Qt event loop exited with code {exit_code}")
            self._stop_vision_loop()
            return exit_code
        else:
            # Tkinter event loop
            self._start_vision_loop()
            try:
                self._ui.run()
            except KeyboardInterrupt:
                pass
            self.shutdown()
            return 0

    def shutdown(self) -> None:
        """Clean shutdown of all components."""
        if self._shutting_down:
            return
        self._shutting_down = True

        self.logger.info("Shutting down Vovy...")

        # Stop vision loop
        self._stop_vision_loop()

        # Stop UI
        if self._ui is not None:
            self.logger.info("Stopping UI...")
            if hasattr(self._ui, "stop"):
                self._ui.stop()

        # Log final stats
        stats = self.vision_agent.get_stats()
        self.logger.info(
            f"Final stats: {stats.iterations} iterations, "
            f"{stats.api_calls} API calls, "
            f"{stats.actions_executed} actions executed, "
            f"{stats.tools_called} MCP tools called, "
            f"{stats.errors} errors"
        )

        self.logger.info(
            "Vovy shutdown complete. "
            "Made by Viperwraith47 — https://github.com/viperwraith47"
        )


# ── Helper ───────────────────────────────────────────────────────────────

def glass_ui_backend_name() -> str:
    """Return a human-readable name for the available UI backend."""
    if PYSIDE6_AVAILABLE:
        return "PySide6 (native Apple Glass)"
    try:
        import tkinter  # noqa: F401
        return "tkinter (simplified, PySide6 not installed)"
    except ImportError:
        return "none (headless mode)"


# ── CLI ────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="vovy",
        description=(
            "Vovy — macOS desktop agent with Apple Glass UI. "
            "Continuously captures the screen, sends to a Vision API, "
            "and executes LLM-returned actions via pyautogui. "
            "Made by Viperwraith47."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 main.py                    # Launch with Apple Glass UI\n"
            "  python3 main.py --headless         # Run vision loop without UI\n"
            "  python3 main.py --model qwen2.5-vl # Use Qwen2.5-VL model\n"
            "  python3 main.py --endpoint http://localhost:11434/v1/chat/completions\n"
            "  python3 main.py --list-models      # List available models\n"
        ),
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Override the vision model (e.g. 'llama-3.2-vision', 'qwen2.5-vl')",
    )
    parser.add_argument(
        "--endpoint", "-e",
        type=str,
        default=None,
        help="Override the API endpoint URL",
    )
    parser.add_argument(
        "--headless", "-H",
        action="store_true",
        help="Run without the Apple Glass UI (vision loop only)",
    )
    parser.add_argument(
        "--list-models", "-l",
        action="store_true",
        help="List available vision models and exit",
    )
    parser.add_argument(
        "--loop-interval", "-i",
        type=float,
        default=None,
        help="Seconds between vision loop iterations (default: 2.0)",
    )
    parser.add_argument(
        "--no-fail-safe",
        action="store_true",
        help="Disable the mouse-top-left fail-safe (NOT RECOMMENDED)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args()


# ── Entry Point ────────────────────────────────────────────────────────────

def main() -> int:
    """Application entry point."""
    args = parse_args()
    app = VovyApp(args)
    try:
        return app.run()
    except Exception as exc:
        if app.logger:
            app.logger.critical(f"Unhandled exception: {exc}", exc_info=True)
        print(f"\n✗ Fatal error: {exc}", file=sys.stderr)
        print("Made by Viperwraith47 — https://github.com/viperwraith47")
        return 1


if __name__ == "__main__":
    sys.exit(main())
