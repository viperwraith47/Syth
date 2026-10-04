#!/usr/bin/env python3
"""
vision_agent.py — OS World Vision Loop & Physical Cursor Action Engine.

This module implements:
  1.  **OS World Vision Loop** — an infinite loop that uses Pillow to capture
      the screen at 1024×768, encodes each frame as a base64 PNG payload,
      sends it to an OpenAI-compatible Vision API, and processes the response.

  2.  **Physical Cursor Action Engine** — parses structured JSON actions
      returned by the Vision API model and maps normalized coordinates
      back to the local monitor grid via ``pyautogui``. Supports human-like
      cursor movement (easing), left/right clicks, continuous scrolling,
      and native string typing.

  3.  **Resilient Automation Safety** — coordinate bounds checking, a
      hardware fail-safe (mouse to top-left corner kills the loop), and
      error logging for missing macOS permissions.

  4.  **MCP Integration** — forwards tool-call requests to the
      ``ToolRegistry`` so the LLM can view files, list directories,
      and execute commands.

Made by Viperwraith47 — https://github.com/viperwraith47
"""

from __future__ import annotations

import base64
import io
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor

import requests

from config import VisionConfig, SafetyConfig, AVAILABLE_MODELS
from mcp_tools import ToolRegistry, ToolResult
from utils import (
    get_screen_size,
    denormalize_coord,
    bounds_check,
    get_easing,
    check_macos_permissions,
)

# ── Types ──────────────────────────────────────────────────────


@dataclass
class VisionStats:
    """Runtime statistics for the vision loop, shared with the UI thread."""

    running: bool = False
    iterations: int = 0
    api_calls: int = 0
    actions_executed: int = 0
    tools_called: int = 0
    errors: int = 0
    last_capture_time: float = 0.0
    last_api_response_time: float = 0.0
    current_model: str = ""
    status_message: str = "Idle"
    capture_resolution: str = "1024×768"
    screen_resolution: str = "0×0"
    permissions: dict[str, bool] = field(default_factory=dict)
    fail_safe_triggered: bool = False
    conversation_turns: int = 0
    last_error: str = ""


@dataclass
class VisionAction:
    """A single parsed action from the LLM response."""

    action_type: str
    params: dict[str, Any]


# ── Main VisionAgent Class ─────────────────────────────────────


class VisionAgent:
    """
    The OS World Vision Loop and Physical Cursor Action Engine.

    Runs as a daemon thread. Captures the screen, sends to the Vision API,
    parses JSON actions, and executes them via pyautogui with human-like
    easing. Includes fail-safe and bounds checking.
    """

    def __init__(
        self,
        vision_config: VisionConfig,
        safety_config: SafetyConfig,
        tool_registry: ToolRegistry,
        logger: logging.Logger,
    ):
        self.config = vision_config
        self.safety = safety_config
        self.tool_registry = tool_registry
        self.logger = logger

        # Threading control
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._api_lock = threading.Lock()  # serialize API calls

        # Screen geometry
        self._screen_w, self._screen_h = get_screen_size()

        # Statistics (thread-safe via _lock)
        self.stats = VisionStats(
            current_model=self.config.display_name(),
            screen_resolution=f"{self._screen_w}×{self._screen_h}",
        )

        # Conversation history for multi-turn LLM interaction
        self._conversation_history: list[dict[str, Any]] = []

        # Permission check (called once at init, can be re-checked)
        self._check_permissions()

        # Thread pool for non-blocking tool execution
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Vovy-Tool")

        self.logger.info(
            f"VisionAgent initialized — screen: {self._screen_w}×{self._screen_h}, "
            f"model: {self.config.display_name()}, "
            f"endpoint: {self.config.endpoint()}"
        )

    # ── Permission Handling ──────────────────────────────────────

    def _check_permissions(self) -> None:
        """Check macOS permissions and log warnings for missing ones."""
        self.stats.permissions = check_macos_permissions(self.logger)

        missing = [k for k, v in self.stats.permissions.items() if not v]
        if missing:
            for perm in missing:
                self.logger.error(
                    f"MISSING macOS PERMISSION: {perm}. "
                    f"This will prevent {'screen capture' if perm == 'screen_recording' else 'mouse/keyboard control'}. "
                    f"Open System Settings → Privacy & Security → {perm.replace('_', ' ').title()} and grant access."
                )
            self.stats.last_error = f"Missing permissions: {', '.join(missing)}"
        else:
            self.logger.info("All macOS permissions granted (Accessibility + Screen Recording).")

    def request_permissions(self) -> None:
        """Prompt the user to grant missing macOS permissions."""
        self.logger.info("Requesting macOS permissions...")
        try:
            from utils import request_permission_prompt
            if not self.stats.permissions.get("accessibility", False):
                request_permission_prompt("accessibility")
            if not self.stats.permissions.get("screen_recording", False):
                request_permission_prompt("screen_recording")
        except Exception as exc:
            self.logger.error(f"Failed to request permissions: {exc}")

    # ── Screen Capture (OS World Vision) ─────────────────────────

    def capture_screen(self) -> str:
        """
        Capture the primary screen using Pillow, resize to 1024×768,
        and encode as a base64 PNG string.

        This is the core of the OS World Vision Loop — each iteration
        produces one base64 payload string that is sent to the Vision API.
        """
        self._update_status("Capturing screen…")

        import pyautogui  # type: ignore[import-not-found]

        start = time.time()

        # Capture full primary screen
        screenshot = pyautogui.screenshot()

        # Resize to the canonical 1024×768 canvas
        screenshot = screenshot.resize((self.config.capture_width, self.config.capture_height))

        # Encode as base64 PNG
        buffer = io.BytesIO()
        screenshot.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        elapsed = time.time() - start

        with self._lock:
            self.stats.last_capture_time = elapsed
            self.stats.status_message = f"Captured 1024×768 in {elapsed:.2f}s ({len(encoded)} bytes base64)"

        self.logger.debug(f"Screen capture: {elapsed:.3f}s, base64 payload {len(encoded)} chars")
        return encoded

    def _capture_fallback(self) -> str:
        """
        Fallback screen capture using the macOS ``screencapture`` command
        if pyautogui/ImageGrab fails (e.g. due to missing permissions).
        """
        import tempfile
        import os
        import subprocess

        tmp_path = os.path.join(tempfile.gettempdir(), "vovy_capture.png")
        try:
            subprocess_result = subprocess.run(
                ["screencapture", "-x", "-R0,0,1024,768", tmp_path],
                capture_output=True, text=True, timeout=10,
            )
            if subprocess_result.returncode == 0 and os.path.exists(tmp_path):
                from PIL import Image  # type: ignore[import-not-found]
                img = Image.open(tmp_path)
                img = img.resize((self.config.capture_width, self.config.capture_height))
                buffer = io.BytesIO()
                img.save(buffer, format="PNG", optimize=True)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                img.close()
                return encoded
            else:
                raise RuntimeError(f"screencapture failed: {subprocess_result.stderr}")
        except Exception as exc:
            self.logger.error(f"Fallback screen capture also failed: {exc}")
            raise
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ── API Request Formatting ───────────────────────────────────

    def build_api_request(self, base64_image: str) -> dict[str, Any]:
        """
        Build an OpenAI-compatible Vision API request payload.

        The payload includes:
          • The system prompt (defines action JSON schema + MCP tools)
          • Conversation history (for multi-turn context)
          • The current base64-encoded screen capture
          • Tool definitions (OpenAI function-calling format) for MCP tools
        """
        # Build the image content block
        image_content = {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64_image}",
            },
        }

        # Build messages array
        messages: list[dict[str, Any]] = []

        # System prompt
        system_msg = {
            "role": "system",
            "content": self.config.system_prompt,
        }
        messages.append(system_msg)

        # Add conversation history (user + assistant turns)
        for hist_msg in self._conversation_history:
            messages.append(hist_msg)

        # Current turn: user sends the screenshot
        user_msg = {
            "role": "user",
            "content": [
                image_content,
                {"type": "text", "text": "Current screen capture (1024x768). "
                                        "Analyze and return JSON actions + tool calls."},
            ],
        }
        messages.append(user_msg)

        # Build request
        model_info = AVAILABLE_MODELS.get(self.config.default_model, {})
        request: dict[str, Any] = {
            "model": self.config.default_model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
        }

        # Attach tool schemas if the model supports native tool calling
        if model_info.get("supports_tools", False):
            tools = self.tool_registry.get_tool_schemas()
            request["tools"] = tools
            request["tool_choice"] = "auto"

        return request

    # ── API Communication ────────────────────────────────────────

    def send_to_api(self, request_payload: dict[str, Any]) -> str:
        """
        Send the vision request to the OpenAI-compatible API endpoint
        and return the raw response text (or parsed JSON).

        Handles authentication, timeouts, and error responses.
        """
        endpoint = self.config.endpoint()
        api_key = self.config.api_key()

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Build the final payload
        payload = dict(request_payload)

        start = time.time()
        try:
            with self._api_lock:
                self._update_status(f"Sending to {self.config.display_name()}…")
                self.logger.debug(f"API request to {endpoint} (payload size: {len(json.dumps(payload))})")

                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

                elapsed = time.time() - start

                if response.status_code != 200:
                    self.logger.error(
                        f"API error {response.status_code}: {response.text[:500]}"
                    )
                    with self._lock:
                        self.stats.errors += 1
                        self.stats.last_error = f"API {response.status_code}: {response.text[:200]}"
                    raise requests.HTTPError(f"API returned {response.status_code}")

                result = response.json()

                with self._lock:
                    self.stats.api_calls += 1
                    self.stats.last_api_response_time = elapsed
                    self.stats.status_message = f"API response in {elapsed:.2f}s"

                self.logger.debug(f"API response received in {elapsed:.3f}s")

                return result

        except requests.ConnectionError as exc:
            self.logger.error(f"Connection error to API ({endpoint}): {exc}")
            with self._lock:
                self.stats.errors += 1
                self.stats.last_error = f"Connection error: {exc}"
            raise
        except requests.Timeout:
            self.logger.error(f"API request timed out (30s) — endpoint: {endpoint}")
            with self._lock:
                self.stats.errors += 1
                self.stats.last_error = "API request timed out"
            raise
        except requests.HTTPError:
            raise  # already logged above
        except Exception as exc:
            self.logger.error(f"Unexpected API error: {exc}", exc_info=True)
            with self._lock:
                self.stats.errors += 1
                self.stats.last_error = f"Unexpected error: {exc}"
            raise

    # ── Response Parsing ─────────────────────────────────────────

    def parse_response(self, api_response: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """
        Parse the Vision API response into:
          1.  Action commands (move, click, scroll, type)
          2.  MCP tool calls (view_file, list_directory, etc.)
          3.  Reasoning text

        Handles both native OpenAI tool-calling format and plain JSON
        text responses (for models like Ollama that don't support
        native tool calling).
        """
        actions: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        reasoning: str = ""

        try:
            if isinstance(api_response, str):
                # Response is raw text — try to parse as JSON
                text = api_response.strip()
                # Strip markdown code fences if present
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                try:
                    parsed = json.loads(text)
                    return self._extract_from_json(parsed)
                except json.JSONDecodeError:
                    # Not JSON — return empty, log warning
                    self.logger.warning(f"Could not parse LLM response as JSON: {text[:200]}")
                    # Fall through to return empty
                    return ([], [], f"Could not parse response: {text[:200]}")

            elif isinstance(api_response, dict):
                # OpenAI-compatible response object
                choices = api_response.get("choices", [])
                if not choices:
                    self.logger.warning("API response has no choices")
                    return ([], [], "No response choices from API")

                choice = choices[0]
                msg = choice.get("message", {})

                # Native tool calls (OpenAI function calling)
                native_tools = msg.get("tool_calls", [])
                for tc in native_tools:
                    fn = tc.get("function", {})
                    tool_calls.append({
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", {}),
                    })

                # Content may be JSON with actions + tool calls
                content = msg.get("content", "")
                if content:
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()

                    try:
                        parsed = json.loads(content)
                        a, tc, r = self._extract_from_json(parsed)
                        actions.extend(a)
                        tool_calls.extend(tc)
                        reasoning = r
                    except json.JSONDecodeError:
                        reasoning = content

                return (actions, tool_calls, reasoning)

            else:
                return ([], [], str(api_response)[:200])

        except Exception as exc:
            self.logger.error(f"Error parsing API response: {exc}", exc_info=True)
            return ([], [], f"Parse error: {exc}")

    def _extract_from_json(self, parsed: dict[str, Any]) -> tuple[list[dict], list[dict], str]:
        """Extract actions, tool_calls, and reasoning from a parsed JSON dict."""
        actions = parsed.get("actions", [])
        if not isinstance(actions, list):
            actions = []

        tool_calls = parsed.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            tool_calls = []

        reasoning = parsed.get("reasoning", parsed.get("thought", ""))

        return (actions, tool_calls, reasoning)

    # ── Action Execution (Physical Cursor Action Engine) ─────────

    def execute_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Execute parsed action commands via pyautogui.

        Supported action types:
          • move   — move cursor with easing (normalized coords [0,1])
          • click  — left/right click (optional normalized coords)
          • scroll — continuous scroll (normalized or absolute units)
          • type   — native string typing via pyautogui.write
          • drag   — drag to position (normalized coords)

        All coordinates are validated and clamped to screen bounds.
        Human-like easing is applied to movement.
        """
        results: list[dict[str, Any]] = []

        try:
            import pyautogui  # type: ignore[import-not-found]
        except ImportError:
            self.logger.error("pyautogui not available — cannot execute actions")
            results.append({"success": False, "error": "pyautogui not installed"})
            return results

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_type = action.get("type", "")
            try:
                if action_type == "move":
                    result = self._execute_move(action, pyautogui)
                elif action_type == "click":
                    result = self._execute_click(action, pyautogui)
                elif action_type == "scroll":
                    result = self._execute_scroll(action, pyautogui)
                elif action_type == "type":
                    result = self._execute_type(action, pyautogui)
                elif action_type == "drag":
                    result = self._execute_drag(action, pyautogui)
                else:
                    result = {"success": False, "error": f"Unknown action type: {action_type}"}

                results.append(result)

                with self._lock:
                    if result.get("success"):
                        self.stats.actions_executed += 1
                    else:
                        self.stats.errors += 1

            except Exception as exc:
                self.logger.error(f"Error executing action '{action_type}': {exc}", exc_info=True)
                with self._lock:
                    self.stats.errors += 1
                results.append({"success": False, "error": str(exc), "action_type": action_type})

        return results

    def _normalize_to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        """Map normalized [0,1] coordinates to absolute screen pixels with bounds checking."""
        if self.safety.clamp_coordinates:
            nx = max(0.0, min(1.0, nx))
            ny = max(0.0, min(1.0, ny))

        x, y = denormalize_coord(nx, ny, self._screen_w, self._screen_h)
        return (x, y)

    def _execute_move(self, action: dict[str, Any], pyautogui) -> dict[str, Any]:
        """Execute a mouse move action with human-like easing."""
        nx = float(action.get("x", 0.5))
        ny = float(action.get("y", 0.5))
        duration = float(action.get("duration", 0.5))
        easing_name = action.get("easing", "easeOutQuad")

        # Bounds checking
        if not bounds_check(nx, ny, 1, 1, clamp=False):
            self.logger.warning(f"Move action out of bounds: x={nx}, y={ny} — clamping")
        if self.safety.clamp_coordinates:
            nx = max(0.0, min(1.0, nx))
            ny = max(0.0, min(1.0, ny))

        # Clamp duration
        duration = max(0.0, min(self.safety.max_move_duration, duration))

        x, y = self._normalize_to_screen(nx, ny)
        ease_fn = get_easing(easing_name)

        self.logger.debug(f"Move: ({nx},{ny}) → ({x},{y}) dur={duration}s easing={easing_name}")
        pyautogui.moveTo(x, y, duration=duration, tween=ease_fn)

        return {
            "success": True,
            "action_type": "move",
            "normalized": (nx, ny),
            "screen": (x, y),
            "duration": duration,
            "easing": easing_name,
        }

    def _execute_click(self, action: dict[str, Any], pyautogui) -> dict[str, Any]:
        """Execute a mouse click action."""
        button = action.get("button", "left")
        clicks = int(action.get("clicks", 1))

        if "x" in action and "y" in action:
            nx = float(action["x"])
            ny = float(action["y"])
            if self.safety.clamp_coordinates:
                nx = max(0.0, min(1.0, nx))
                ny = max(0.0, min(1.0, ny))
            x, y = self._normalize_to_screen(nx, ny)
        else:
            # Click at current position
            x, y = None, None

        btn_map = {"left": "left", "right": "right", "middle": "middle"}
        btn = btn_map.get(button, "left")

        self.logger.debug(f"Click: button={btn} clicks={clicks} at=({x},{y})")
        if x is not None and y is not None:
            pyautogui.click(x=x, y=y, button=btn, clicks=clicks)
        else:
            pyautogui.click(button=btn, clicks=clicks)

        return {
            "success": True,
            "action_type": "click",
            "button": btn,
            "clicks": clicks,
            "at": (x, y) if x is not None else "current",
        }

    def _execute_scroll(self, action: dict[str, Any], pyautogui) -> dict[str, Any]:
        """Execute a scroll action."""
        amount = int(action.get("amount", 0))
        horizontal = bool(action.get("horizontal", False))

        # Clamp scroll amount
        max_delta = self.safety.max_scroll_delta
        if self.safety.clamp_coordinates:
            amount = max(-max_delta, min(max_delta, amount))

        self.logger.debug(f"Scroll: amount={amount} horizontal={horizontal}")
        if horizontal:
            pyautogui.hscroll(amount)
        else:
            pyautogui.scroll(amount)

        return {
            "success": True,
            "action_type": "scroll",
            "amount": amount,
            "horizontal": horizontal,
        }

    def _execute_type(self, action: dict[str, Any], pyautogui) -> dict[str, Any]:
        """Execute a text typing action (native string typing)."""
        text = str(action.get("text", ""))
        interval = float(action.get("interval", 0.05))
        interval = max(0.0, min(1.0, interval))

        self.logger.debug(f"Type: {len(text)} chars interval={interval}")
        pyautogui.write(text, interval=interval)

        return {
            "success": True,
            "action_type": "type",
            "character_count": len(text),
            "interval": interval,
        }

    def _execute_drag(self, action: dict[str, Any], pyautogui) -> dict[str, Any]:
        """Execute a drag action (move + hold + release)."""
        nx = float(action.get("x", 0.5))
        ny = float(action.get("y", 0.5))
        duration = float(action.get("duration", 0.5))
        button = action.get("button", "left")

        if self.safety.clamp_coordinates:
            nx = max(0.0, min(1.0, nx))
            ny = max(0.0, min(1.0, ny))

        x, y = self._normalize_to_screen(nx, ny)
        btn = {"left": "left", "right": "right", "middle": "middle"}.get(button, "left")

        self.logger.debug(f"Drag: to ({x},{y}) dur={duration}s button={btn}")
        pyautogui.mouseDown(button=btn)
        pyautogui.moveTo(x, y, duration=duration)
        pyautogui.mouseUp(button=btn)

        return {
            "success": True,
            "action_type": "drag",
            "screen": (x, y),
            "duration": duration,
            "button": btn,
        }

    # ── MCP Tool Execution ───────────────────────────────────────

    def execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Execute MCP tool calls discovered from the LLM response.

        Each tool call is dispatched to the ToolRegistry. Results are
        returned in the same order for logging and conversation context.
        """
        results: list[dict[str, Any]] = []

        for tc in tool_calls:
            name = tc.get("name", "")
            arguments = tc.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}

            self.logger.debug(f"Executing MCP tool: {name}({arguments})")
            try:
                result: ToolResult = self.tool_registry.call_tool(name, **arguments)
                results.append({
                    "tool": name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "metadata": result.metadata,
                })

                with self._lock:
                    self.stats.tools_called += 1
                    if not result.success:
                        self.stats.errors += 1

            except Exception as exc:
                self.logger.error(f"MCP tool '{name}' failed: {exc}", exc_info=True)
                results.append({
                    "tool": name,
                    "success": False,
                    "error": str(exc),
                })
                with self._lock:
                    self.stats.errors += 1

        return results

    # ── Fail-Safe ────────────────────────────────────────────────

    def check_fail_safe(self) -> bool:
        """
        Hardware fail-safe: if the physical mouse cursor is at the
        top-left corner of the screen (within the configured radius),
        terminate the execution loop.

        This is checked at the start of each loop iteration.
        """
        if not self.safety.enable_fail_safe:
            return False

        try:
            import pyautogui  # type: ignore[import-not-found]
            x, y = pyautogui.position()
        except Exception as exc:
            self.logger.warning(f"Could not read mouse position for fail-safe: {exc}")
            return False

        corner_x, corner_y = self.safety.fail_safe_corner
        radius = self.safety.fail_safe_radius
        distance = ((x - corner_x) ** 2 + (y - corner_y) ** 2) ** 0.5

        if distance <= radius:
            self.logger.critical(
                f"FAIL-SAFE TRIGGERED: Mouse at ({x}, {y}) near "
                f"corner ({corner_x}, {corner_y}) — terminating execution loop."
            )
            with self._lock:
                self.stats.fail_safe_triggered = True
            return True

        return False

    # ── Conversation Management ──────────────────────────────────

    def _update_conversation(self, actions_result: list[dict], tools_result: list[dict], reasoning: str) -> None:
        """
        Add the LLM's response and tool results to the conversation history.
        The conversation is trimmed to avoid exceeding token limits.
        """
        # Add the assistant's response (actions + tool calls) as a message
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": reasoning or ""}

        # Trim conversation if too long (keep last 10 turns)
        max_messages = 10
        if len(self._conversation_history) > max_messages * 2:
            self._conversation_history = self._conversation_history[-(max_messages * 2):]

        # Add tool results to history for the next turn
        tool_results_msg: dict[str, Any] = {
            "role": "tool",
            "content": json.dumps({
                "actions_executed": actions_result,
                "tool_results": tools_result,
            }, default=str),
        }

        self._conversation_history.append(assistant_msg)
        if tools_result:
            self._conversation_history.append(tool_results_msg)

    # ── Status & Statistics ──────────────────────────────────────

    def _update_status(self, message: str) -> None:
        """Thread-safe status message update."""
        with self._lock:
            self.stats.status_message = message

    def get_stats(self) -> VisionStats:
        """Return a thread-safe copy of the current stats."""
        with self._lock:
            return VisionStats(
                running=self.stats.running,
                iterations=self.stats.iterations,
                api_calls=self.stats.api_calls,
                actions_executed=self.stats.actions_executed,
                tools_called=self.stats.tools_called,
                errors=self.stats.errors,
                last_capture_time=self.stats.last_capture_time,
                last_api_response_time=self.stats.last_api_response_time,
                current_model=self.stats.current_model,
                status_message=self.stats.status_message,
                capture_resolution=self.stats.capture_resolution,
                screen_resolution=self.stats.screen_resolution,
                permissions=dict(self.stats.permissions),
                fail_safe_triggered=self.stats.fail_safe_triggered,
                conversation_turns=self.stats.conversation_turns,
                last_error=self.stats.last_error,
            )

    # ── Main Loop ────────────────────────────────────────────────

    def run(self) -> None:
        """
        The infinite OS World Vision Loop.

        Each iteration:
          1. Check fail-safe (mouse at top-left corner → stop)
          2. Capture screen at 1024×768 via Pillow
          3. Encode as base64 PNG payload
          4. Build & send OpenAI-compatible API request
          5. Parse JSON actions + MCP tool calls from response
          6. Execute actions via pyautogui (human-like easing)
          7. Execute MCP tool calls via ToolRegistry
          8. Update conversation history
          9. Wait for loop_interval, repeat
        """
        with self._lock:
            self.stats.running = True
            self.stats.conversation_turns = 0

        self.logger.info("OS World Vision Loop started — infinite execution mode")
        self.logger.info(f"Model: {self.config.display_name()} | Endpoint: {self.config.endpoint()}")
        self.logger.info(f"Fail-safe: top-left corner within {self.safety.fail_safe_radius}px")

        # Clear conversation history at start
        self._conversation_history.clear()

        while not self._stop_event.is_set():
            try:
                # ── Step 1: Fail-safe check ────────────────────────
                if self.check_fail_safe():
                    self.logger.info("Vision loop terminated by fail-safe.")
                    break

                with self._lock:
                    self.stats.iterations += 1
                    self.stats.conversation_turns += 1

                # ── Step 2: Capture screen ─────────────────────────
                self._update_status("Capturing screen…")
                try:
                    base64_image = self.capture_screen()
                except Exception as exc:
                    self.logger.error(f"Screen capture failed: {exc}")
                    self._update_status(f"Capture error: {exc}")
                    # Wait and retry
                    self._stop_event.wait(timeout=self.config.loop_interval)
                    continue

                # ── Step 3: Build & send API request ────────────────
                request_payload = self.build_api_request(base64_image)

                self._update_status("Sending to Vision API…")
                try:
                    api_response = self.send_to_api(request_payload)
                except Exception as exc:
                    self.logger.error(f"API request failed: {exc}")
                    self._update_status(f"API error: {exc}")
                    self._stop_event.wait(timeout=self.config.loop_interval)
                    continue

                # ── Step 4: Parse response ──────────────────────────
                actions, tool_calls, reasoning = self.parse_response(api_response)
                self.logger.debug(
                    f"Parsed: {len(actions)} actions, {len(tool_calls)} tool calls, "
                    f"reasoning={reasoning[:100]}"
                )

                # ── Step 5: Execute actions ─────────────────────────
                if actions:
                    self._update_status(f"Executing {len(actions)} actions…")
                    action_results = self.execute_actions(actions)
                    for r in action_results:
                        if not r.get("success"):
                            self.logger.warning(f"Action failed: {r}")
                else:
                    action_results = []

                # ── Step 6: Execute MCP tool calls ──────────────────
                if tool_calls:
                    self._update_status(f"Executing {len(tool_calls)} MCP tools…")
                    tool_results = self.execute_tool_calls(tool_calls)
                else:
                    tool_results = []

                # ── Step 7: Update conversation ─────────────────────
                self._update_conversation(action_results, tool_results, reasoning)

                # ── Step 8: Wait ────────────────────────────────────
                self._update_status("Idle — waiting…")
                self._stop_event.wait(timeout=self.config.loop_interval)

            except Exception as exc:
                self.logger.error(
                    f"Unhandled error in vision loop iteration {self.stats.iterations}: {exc}",
                    exc_info=True,
                )
                with self._lock:
                    self.stats.errors += 1
                    self.stats.last_error = str(exc)
                self._stop_event.wait(timeout=self.config.loop_interval)

        with self._lock:
            self.stats.running = False
            self.stats.status_message = "Stopped"

        self.logger.info("OS World Vision Loop terminated.")

    # ── Control ──────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the vision loop to stop gracefully."""
        self.logger.info("Stop signal received — halting vision loop…")
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        """Check if the vision loop is currently running."""
        return not self._stop_event.is_set() and self.stats.running

    # ── Model Management ─────────────────────────────────────────

    def switch_model(self, model_slug: str) -> bool:
        """Toggle the active vision model at runtime."""
        if model_slug in AVAILABLE_MODELS:
            self.config.default_model = model_slug
            with self._lock:
                self.stats.current_model = self.config.display_name()
            self.logger.info(f"Model switched to: {self.config.display_name()}")
            return True
        self.logger.warning(f"Unknown model slug: {model_slug}")
        return False

    def list_available_models(self) -> list[dict[str, Any]]:
        """Return list of available models with display info."""
        models = []
        for slug, info in AVAILABLE_MODELS.items():
            models.append({
                "slug": slug,
                "display_name": info["display_name"],
                "description": info["description"],
                "endpoint": info["endpoint"],
                "is_active": slug == self.config.default_model,
            })
        return models
