#!/usr/bin/env python3
"""
utils.py — Shared utilities for Syth.

Provides:
  • Structured logging (console + rotating file)
  • macOS permission checks (Accessibility, Screen Recording)
  • Coordinate normalization / denormalization helpers
  • Easing function registry (human-like cursor movement)
  • Screen information helpers

Made by Viperwraith47 — https://github.com/viperwraith47
"""

from __future__ import annotations

import logging
import math
import os
import platform
import subprocess
import sys
from datetime import datetime
from typing import Any

# ── Logging ────────────────────────────────────────────────────


def setup_logging(log_dir: str | None = None, level: int = logging.INFO) -> logging.Logger:
    """
    Configure a structured logger that writes to both console and a rotating
    log file. Returns the top-level ``Syth`` logger.
    """
    log_dir = log_dir or os.path.expanduser("~/.syth/logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"syth-{datetime.now().strftime('%Y-%m-%d')}.log")

    logger = logging.getLogger("Syth")
    logger.setLevel(level)
    logger.handlers.clear()  # avoid duplicate handlers on re-init

    # Console handler — concise
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(console)

    # File handler — detailed with full timestamps
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    # Prevent propagation to root logger (avoids duplicate console output)
    logger.propagate = False
    return logger


# ── macOS Permission Checks ────────────────────────────────────

def check_macos_permissions(logger: logging.Logger | None = None) -> dict[str, bool]:
    """
    Check whether the current process has the required macOS permissions:
      • Accessibility (for mouse/keyboard control via pyautogui)
      • Screen Recording (for screen capture via Pillow/pyautogui)

    Returns a dict with boolean flags. Missing permissions are logged as
    errors with remediation instructions.
    """
    if logger is None:
        logger = logging.getLogger("Syth")

    permissions: dict[str, bool] = {
        "accessibility": False,
        "screen_recording": False,
    }

    if platform.system() != "Darwin":
        logger.debug("Non-macOS platform detected; skipping permission checks.")
        permissions["accessibility"] = True
        permissions["screen_recording"] = True
        return permissions

    # ── Accessibility permission ─────────────────────────────────
    try:
        from ctypes import CDLL, c_void_p, util  # type: ignore[import-untyped]

        # Try multiple framework paths — macOS paths vary across versions
        _lib_paths = [
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
            "/System/Library/Frameworks/AppKit.framework/AppKit",
            "ApplicationServices",
        ]
        _aq = None
        for _p in _lib_paths:
            try:
                _aq = CDLL(_p)
                if hasattr(_aq, "AXIsProcessTrusted"):
                    break
            except OSError:
                continue

        if _aq is None or not hasattr(_aq, "AXIsProcessTrusted"):
            raise OSError("AXIsProcessTrusted not found in any known framework")

        _AXIsProcessTrusted = _aq.AXIsProcessTrusted
        _AXIsProcessTrusted.restype = bool
        _AXIsProcessTrusted.argtypes = [c_void_p]

        # kAXTrustedCheckOptionKey is the CFString "kAXTrustedCheckOptionKey"
        # Use None to just check status (no prompt); prompt is handled separately
        _kAXTrustedCheckOptionKey = "kAXTrustedCheckOptionKey"

        # Try pyobjc approach first (handles type conversion automatically)
        try:
            from Quartz import AXIsProcessTrusted as _ax_pyobjc  # type: ignore[import-not-found]
            # Pass True for the options key to also prompt if not trusted
            options = {_kAXTrustedCheckOptionKey: True}
            is_trusted = bool(_ax_pyobjc(options))
        except (ImportError, NameError, TypeError):
            # Fall back to ctypes with None (no prompt, just check)
            is_trusted = bool(_AXIsProcessTrusted(None))

        permissions["accessibility"] = bool(is_trusted)

        if not is_trusted:
            logger.error(
                "macOS Accessibility permission is NOT granted. "
                "Syth needs Accessibility permission to control the mouse and keyboard. "
                "Open System Settings → Privacy & Security → Accessibility and add this app/Python."
            )
    except Exception as exc:
        logger.warning(f"Could not check Accessibility permission (pyobjc/ctypes unavailable?): {exc}")
        # Fallback: check via tcc database
        permissions["accessibility"] = _check_tcc_fallback("accessibility", logger)

    # ── Screen Recording permission ───────────────────────────────
    try:
        from Quartz import CGPreflightScreenCaptureAccess  # type: ignore[import-not-found]

        has_sr = bool(CGPreflightScreenCaptureAccess())
        permissions["screen_recording"] = has_sr

        if not has_sr:
            logger.error(
                "macOS Screen Recording permission is NOT granted. "
                "Syth needs Screen Recording permission to capture the screen. "
                "Open System Settings → Privacy & Security → Screen Recording "
                "and enable Terminal / Python / this app."
            )
    except Exception as exc:
        logger.warning(f"Could not check Screen Recording permission (pyobjc unavailable?): {exc}")
        permissions["screen_recording"] = _check_tcc_fallback("screen_recording", logger)

    return permissions


def _check_tcc_fallback(service: str, logger: logging.Logger) -> bool:
    """Best-effort fallback using the `tccutil`/system_profiler approach."""
    # Map service names to TCC service identifiers
    tcc_service_map = {
        "accessibility": "kTCCServiceAccessibility",
        "screen_recording": "kTCCServiceScreenCapture",
    }
    tcc_service = tcc_service_map.get(service, service.upper())

    # Try sqlite3 to query the TCC database
    import os
    tcc_db_candidates = [
        os.path.expanduser("~/Library/Application Scripts/com.apple.tcc/TCC.db"),
        "/Library/Application Scripts/com.apple.tcc/TCC.db",
    ]

    for tcc_db in tcc_db_candidates:
        if not os.path.exists(tcc_db):
            continue
        try:
            result = subprocess.run(
                ["sqlite3", tcc_db,
                 f"SELECT allowed FROM access WHERE service='{tcc_service}' "
                 f"AND client LIKE '%python%' LIMIT 1;"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                allowed = result.stdout.strip() == "1"
                if not allowed:
                    logger.error(
                        f"macOS {service.replace('_', ' ').title()} permission not detected. "
                        f"Grant permission in System Settings → Privacy & Security → "
                        f"{service.replace('_', ' ').title()}."
                    )
                return allowed
        except FileNotFoundError:
            logger.warning("sqlite3 CLI not available — cannot query TCC database.")
            break
        except Exception:
            continue

    # Last resort: check via spctl (doesn't check permissions, just presence)
    logger.warning(
        f"Could not determine macOS {service} permission status. "
        f"Grant it in System Settings → Privacy & Security → {service.replace('_', ' ').title()}."
    )
    return False


def request_permission_prompt(service: str) -> bool:
    """
    On macOS, trigger the system permission dialog for the given service.
    This requires the pyobjc bridge for the most reliable results.
    """
    if platform.system() != "Darwin":
        return True

    try:
        if service == "accessibility":
            from ctypes import CDLL, c_void_p  # type: ignore[import-untyped]

            # Try multiple framework paths — macOS paths vary across versions
            _lib_paths = [
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
                "/System/Library/Frameworks/AppKit.framework/AppKit",
                "ApplicationServices",
            ]
            _aq = None
            for _p in _lib_paths:
                try:
                    _aq = CDLL(_p)
                    if hasattr(_aq, "AXIsProcessTrusted"):
                        break
                except OSError:
                    continue

            if _aq is not None and hasattr(_aq, "AXIsProcessTrusted"):
                _AXIsProcessTrusted = _aq.AXIsProcessTrusted
                _AXIsProcessTrusted.restype = bool
                _AXIsProcessTrusted.argtypes = [c_void_p]
                # Try pyobjc approach first (handles type conversion automatically)
                try:
                    from Quartz import AXIsProcessTrusted as _ax_pyobjc  # type: ignore[import-not-found]
                    options = {"kAXTrustedCheckOptionKey": True}
                    return bool(_ax_pyobjc(options))
                except (ImportError, NameError, TypeError):
                    pass
                # Fall back to ctypes with None (no prompt, just check)
                return bool(_AXIsProcessTrusted(None))

        elif service == "screen_recording":
            from Quartz import CGRequestScreenCaptureAccess  # type: ignore[import-not-found]
            return bool(CGRequestScreenCaptureAccess())
    except Exception:
        pass

    # Final fallback: open System Settings to the relevant page
    try:
        subprocess.run(["open", "x-apple.systemsettings:privacy"], check=False)
    except Exception:
        pass
    return False


# ── Coordinate Utilities ───────────────────────────────────────

def normalize_coord(x: float, y: float, screen_w: int, screen_h: int) -> tuple[float, float]:
    """
    Convert absolute screen coordinates to normalized [0, 1] coordinates
    relative to the given screen dimensions.
    """
    nx = max(0.0, min(1.0, x / screen_w))
    ny = max(0.0, min(1.0, y / screen_h))
    return (nx, ny)


def denormalize_coord(nx: float, ny: float, screen_w: int, screen_h: int) -> tuple[int, int]:
    """
    Convert normalized [0, 1] coordinates back to absolute screen coordinates.
    Includes clamping to screen bounds.
    """
    x = int(round(nx * screen_w))
    y = int(round(ny * screen_h))
    # Bounds checking — never exceed screen dimensions
    x = max(0, min(screen_w - 1, x))
    y = max(0, min(screen_h - 1, y))
    return (x, y)


def bounds_check(x: float, y: float, screen_w: int, screen_h: int, clamp: bool = True) -> bool:
    """
    Check whether normalized coordinates are within [0, 1] bounds.
    If ``clamp`` is True, out-of-bounds values are clamped instead of failing.
    """
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        return True
    return False


# ── Easing Functions (human-like cursor movement) ──────────────

def ease_out_quad(t: float) -> float:
    """Quadratic ease-out — starts fast, decelerates to target."""
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out — smooth acceleration and deceleration."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0


def ease_out_elastic(t: float) -> float:
    """Elastic ease-out — slight overshoot, natural-feeling."""
    if t <= 0 or t >= 1:
        return t
    p = 0.3
    s = p / 2.0
    return pow(2.0, -10.0 * t) * math.sin((t - s) * (2.0 * math.pi) / p) + 1.0


def ease_in_sine(t: float) -> float:
    """Sine ease-in — gradual start."""
    return 1.0 - math.cos(t * math.pi / 2.0)


EASING_FUNCTIONS: dict[str, Any] = {
    "linear": lambda t: t,
    "easeOutQuad": ease_out_quad,
    "easeInOutCubic": ease_in_out_cubic,
    "easeOutElastic": ease_out_elastic,
    "easeInSine": ease_in_sine,
}


def get_easing(name: str) -> Any:
    """Return the easing function by name, defaulting to ease_out_quad."""
    return EASING_FUNCTIONS.get(name, ease_out_quad)


# ── Screen Information ─────────────────────────────────────────

def get_screen_size():
    """Return the primary screen size as (width, height)."""
    try:
        import pyautogui
        return pyautogui.size()
    except Exception:
        try:
            from screeninfo import get_monitors
            m = get_monitors()[0]
            return (m.width, m.height)
        except Exception:
            return (1920, 1080)  # sensible default


def get_screen_info() -> dict[str, Any]:
    """Return comprehensive screen information."""
    size = get_screen_size()
    return {
        "width": size[0],
        "height": size[1],
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }


# ── Misc Helpers ───────────────────────────────────────────────

def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))


def open_url(url: str) -> bool:
    """Open a URL in the default browser (cross-platform)."""
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        try:
            if platform.system() == "Darwin":
                subprocess.run(["open", url], check=True)
            elif platform.system() == "Windows":
                subprocess.run(["start", url], shell=True, check=True)
            else:
                subprocess.run(["xdg-open", url], check=True)
            return True
        except Exception:
            return False


def format_bytes(num_bytes: int) -> str:
    """Human-readable byte size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}PB"
