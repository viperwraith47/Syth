#!/usr/bin/env python3
"""
mcp_tools.py — Google Stitch Model Context Protocol (MCP) tool definitions.

Implements the MCP tool specification as structured, callable system functions
that an OpenAI-compatible Vision API model can discover and invoke. Each tool
is registered with a JSON-schema-compatible input spec so the LLM can request
file inspection, directory listing, shell commands, cursor actions, and
screenshot capture.

Made by Viperwraith47 — https://github.com/viperwraith47
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Lazy imports — pyautogui and PIL are only needed when the corresponding
# tools are actually invoked, and may not be installed in a headless
# test environment.

logger = logging.getLogger("Syth.MCP")

# ── MCP Tool Base Classes ──────────────────────────────────────


@dataclass
class ToolResult:
    """Structured result returned by a tool execution."""

    success: bool
    output: str
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class MCPTool(ABC):
    """
    Base class for all MCP tools.

    Each subclass defines:
      • ``name``      — unique tool identifier (e.g. "view_file")
      • ``description`` — human-readable description for the LLM
      • ``input_schema`` — JSON Schema dict describing accepted parameters
      • ``execute()`` — the actual implementation
    """

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    _input_schema_dict: dict[str, Any] = field(default_factory=dict, init=False)

    @classmethod
    @property
    def schema(cls) -> dict[str, Any]:
        """Return the OpenAI-compatible function-calling schema."""
        properties = getattr(cls, "input_schema", {})
        required_fields: list[str] = []

        # Walk MRO to gather input_schema from base class
        for klass in cls.__mro__:
            if hasattr(klass, "input_schema"):
                schema = getattr(klass, "input_schema")
                if isinstance(schema, dict) and schema:
                    # Collect required fields
                    if "required" in schema:
                        required_fields.extend(schema["required"])
                    # Merge properties
                    merged = {}
                    for key, val in schema.items():
                        if key == "required":
                            continue
                        if key == "properties" and isinstance(val, dict):
                            merged.update(val)
                    return {
                        "type": "function",
                        "function": {
                            "name": cls.name,
                            "description": cls.description,
                            "parameters": {
                                "type": "object",
                                "properties": merged,
                                "required": list(set(required_fields)),
                            },
                        },
                    }

        # Fallback: build from input_schema dict
        if isinstance(properties, dict):
            props = {}
            reqs = []
            for k, v in properties.items():
                if isinstance(v, dict):
                    props[k] = v
                    if v.get("required"):
                        reqs.append(k)
            return {
                "type": "function",
                "function": {
                    "name": cls.name,
                    "description": cls.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": reqs,
                    },
                },
            }
        return {"type": "function", "function": {"name": cls.name, "description": cls.description, "parameters": {"type": "object", "properties": {}, "required": []}}}

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments. Override in subclass."""
        ...


# ── File System Tools ──────────────────────────────────────────


class ViewFileTool(MCPTool):
    """Read and return the contents of a file on the local filesystem."""

    name = "view_file"
    description = (
        "Read the text contents of a file at the given absolute path. "
        "Returns up to 200 lines of content. Binary files will return a notice. "
        "Use this when you need to inspect code, logs, configs, or any text file."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to read (e.g. /Users/me/Documents/code/main.py).",
            },
        },
        "required": ["path"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return ToolResult(success=False, error=f"File not found: {path}")

            if not p.is_file():
                return ToolResult(success=False, error=f"Not a file: {path}")

            # Guard against binary files
            size = p.stat().st_size
            if size > 2_000_000:  # > 2MB
                return ToolResult(
                    success=True,
                    output=f"[File is {size} bytes — truncated] "
                           f"Use a more targeted approach for large files.",
                    metadata={"path": str(p), "size": size},
                )

            raw = p.read_bytes()
            try:
                content = raw.decode("utf-8", errors="replace")
            except Exception:
                content = raw.decode("latin-1", errors="replace")

            lines = content.splitlines()
            if len(lines) > 200:
                content = "\n".join(lines[:200])
                truncated_msg = f"\n[...truncated: {len(lines) - 200} more lines]"
            else:
                truncated_msg = ""

            return ToolResult(
                success=True,
                output=content + truncated_msg,
                metadata={"path": str(p), "size_bytes": size, "lines": len(lines)},
            )
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {path}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Error reading {path}: {exc}")


class ListDirectoryTool(MCPTool):
    """List the contents of a directory on the local filesystem."""

    name = "list_directory"
    description = (
        "List the immediate contents of a directory at the given path. "
        "Returns entries with type (file/dir/symlink) and sizes for files."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the directory (default: current working directory).",
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", os.getcwd())
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return ToolResult(success=False, error=f"Directory not found: {path}")
            if not p.is_dir():
                return ToolResult(success=False, error=f"Not a directory: {path}")

            entries = []
            for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                try:
                    stat = entry.stat()
                    entry_type = "dir" if entry.is_dir() else "file" if entry.is_file() else "symlink"
                    size = "" if entry_type == "dir" else f" ({stat.st_size} bytes)"
                    entries.append(f"  {'📁' if entry_type == 'dir' else '📄'} {entry.name}{size}")
                except PermissionError:
                    entries.append(f"  {'📁' if entry.is_dir() else '📄'} {entry.name} (permission denied)")

            if not entries:
                content = "[empty directory]"
            else:
                content = f"{p}\n" + "\n".join(entries)

            return ToolResult(
                success=True,
                output=content,
                metadata={"path": str(p), "entry_count": len(entries)},
            )
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {path}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Error listing {path}: {exc}")


class ExecuteCommandTool(MCPTool):
    """Execute a shell command on the local system and return its output."""

    name = "execute_command"
    description = (
        "Execute a shell command and return stdout/stderr. "
        "Use for running scripts, checking system status, git operations, etc. "
        "Set a timeout (default 30s). Commands run in the current working directory."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute (e.g. 'git status' or 'echo hello').",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in seconds (default: 30).",
                "default": 30,
            },
            "cwd": {
                "type": "string",
                "description": "Working directory to run the command in (default: current directory).",
            },
        },
        "required": ["command"],
    }

    # Block dangerous commands that could cause harm
    _BLOCKED_PATTERNS = [
        "rm -rf /",
        "mkfs",
        "dd if=",
        ":(){:|:&};:",
    ]

    def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", 30)
        cwd = kwargs.get("cwd") or os.getcwd()

        # Safety: block destructive commands
        for blocked in self._BLOCKED_PATTERNS:
            if blocked in command:
                return ToolResult(
                    success=False,
                    error=f"Blocked potentially destructive command pattern: '{blocked}'",
                )

        try:
            logger.info(f"Executing command: {command} (cwd={cwd}), timeout={timeout}s")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            output = result.stdout if result.stdout else ""
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            return ToolResult(
                success=result.returncode == 0,
                output=output or "[no output]",
                error="" if result.returncode == 0 else f"Exit code: {result.returncode}",
                metadata={
                    "command": command,
                    "returncode": result.returncode,
                    "cwd": cwd,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Command timed out after {timeout}s: {command}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Error executing command: {exc}")


# ── Cursor / Input Tools ───────────────────────────────────────


class GetMousePositionTool(MCPTool):
    """Get the current global mouse cursor position."""

    name = "get_mouse_position"
    description = "Return the current (x, y) pixel coordinates of the mouse cursor on the screen."
    input_schema: dict[str, Any] = {}
    _required: list[str] = []

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]
            x, y = pyautogui.position()
            return ToolResult(
                success=True,
                output=f"Mouse position: x={x}, y={y}",
                metadata={"x": x, "y": y},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Could not get mouse position: {exc}")


class MoveCursorTool(MCPTool):
    """Move the mouse cursor to a target position with human-like easing."""

    name = "move_cursor"
    description = (
        "Move the mouse cursor to the given (x, y) pixel coordinates on screen "
        "with human-like easing. Coordinates must be within screen bounds."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "x": {
                "type": "integer",
                "description": "Target X coordinate in pixels (0 to screen width).",
            },
            "y": {
                "type": "integer",
                "description": "Target Y coordinate in pixels (0 to screen height).",
            },
            "duration": {
                "type": "number",
                "description": "Movement duration in seconds (default 0.5). Higher = slower.",
                "default": 0.5,
            },
            "easing": {
                "type": "string",
                "description": "Easing function: linear, easeOutQuad, easeInOutCubic, easeOutElastic, easeInSine.",
                "default": "easeOutQuad",
            },
        },
        "required": ["x", "y"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]
            from utils import get_screen_size, bounds_check, get_easing

            x = int(kwargs.get("x", 0))
            y = int(kwargs.get("y", 0))
            duration = float(kwargs.get("duration", 0.5))
            easing_name = kwargs.get("easing", "easeOutQuad")

            screen_w, screen_h = get_screen_size()

            # Bounds checking — clamp to screen
            x = max(0, min(screen_w - 1, x))
            y = max(0, min(screen_h - 1, y))

            # Use pyautogui's moveTo with tween for human-like motion
            ease_fn = get_easing(easing_name)
            pyautogui.moveTo(x, y, duration=duration, tween=ease_fn)

            return ToolResult(
                success=True,
                output=f"Moved cursor to ({x}, {y}) over {duration}s using {easing_name}",
                metadata={"x": x, "y": y, "duration": duration, "screen_size": [screen_w, screen_h]},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Error moving cursor: {exc}")


class ClickAtTool(MCPTool):
    """Click the mouse at a given screen position."""

    name = "click_at"
    description = (
        "Click the mouse at the given (x, y) pixel coordinates. "
        "Optionally specify left/right click and number of clicks."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "x": {"type": "integer", "description": "X coordinate in pixels."},
            "y": {"type": "integer", "description": "Y coordinate in pixels."},
            "button": {
                "type": "string",
                "description": "Mouse button: 'left' or 'right' (default: 'left').",
                "enum": ["left", "right", "middle"],
                "default": "left",
            },
            "clicks": {
                "type": "integer",
                "description": "Number of clicks (default: 1).",
                "default": 1,
            },
        },
        "required": ["x", "y"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]
            from utils import get_screen_size

            x = int(kwargs.get("x", 0))
            y = int(kwargs.get("y", 0))
            button = kwargs.get("button", "left")
            clicks = int(kwargs.get("clicks", 1))

            screen_w, screen_h = get_screen_size()
            x = max(0, min(screen_w - 1, x))
            y = max(0, min(screen_h - 1, y))

            # Map button names
            btn_map = {"left": "left", "right": "right", "middle": "middle"}
            btn = btn_map.get(button, "left")

            pyautogui.click(x=x, y=y, button=btn, clicks=clicks)

            return ToolResult(
                success=True,
                output=f"Clicked {button} at ({x}, {y}) x{clicks}",
                metadata={"x": x, "y": y, "button": button, "clicks": clicks},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Error clicking: {exc}")


class ScrollAtTool(MCPTool):
    """Scroll the mouse wheel at the current or specified position."""

    name = "scroll_at"
    description = "Scroll the mouse wheel. Positive = up/forward, negative = down/backward."
    input_schema: dict[str, Any] = {
        "properties": {
            "amount": {
                "type": "integer",
                "description": "Number of scroll units. Positive scrolls up, negative down.",
            },
            "horizontal": {
                "type": "boolean",
                "description": "If true, scroll horizontally (default: false, vertical).",
                "default": False,
            },
        },
        "required": ["amount"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]
            amount = int(kwargs.get("amount", 0))
            horizontal = bool(kwargs.get("horizontal", False))

            if horizontal:
                pyautogui.hscroll(amount)
            else:
                pyautogui.scroll(amount)

            direction = "up" if amount > 0 else "down" if amount < 0 else "none"
            return ToolResult(
                success=True,
                output=f"Scrolled {abs(amount)} units {direction}{' (horizontal)' if horizontal else ''}",
                metadata={"amount": amount, "direction": direction, "horizontal": horizontal},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Error scrolling: {exc}")


class TypeTextTool(MCPTool):
    """Type text using pyautogui.write (native string typing)."""

    name = "type_text"
    description = (
        "Type a string of text at the current cursor position using native keyboard "
        "input. Supports special keys like 'enter', 'tab', 'backspace', 'space'. "
        "For special key sequences, use a list of key names."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "text": {
                "type": "string",
                "description": "The text string to type.",
            },
            "interval": {
                "type": "number",
                "description": "Delay between key presses in seconds (default: 0.05).",
                "default": 0.05,
            },
        },
        "required": ["text"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]
            text = kwargs.get("text", "")
            interval = float(kwargs.get("interval", 0.05))

            pyautogui.write(text, interval=interval)

            return ToolResult(
                success=True,
                output=f"Typed {len(text)} characters: '{text[:50]}{'...' if len(text) > 50 else ''}'",
                metadata={"character_count": len(text), "interval": interval},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Error typing: {exc}")


class TakeScreenshotTool(MCPTool):
    """Capture a screenshot of the entire screen or a region."""

    name = "take_screenshot"
    description = (
        "Capture a screenshot. Optionally specify a region (x, y, width, height). "
        "Returns the image as a base64-encoded PNG string. Without a region, "
        "captures the full primary screen."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "x": {"type": "integer", "description": "Region X offset (default: 0).", "default": 0},
            "y": {"type": "integer", "description": "Region Y offset (default: 0).", "default": 0},
            "width": {"type": "integer", "description": "Region width (default: full screen)."},
            "height": {"type": "integer", "description": "Region height (default: full screen)."},
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]
            import io
            import base64
            from PIL import Image  # type: ignore[import-not-found]

            x = kwargs.get("x", 0)
            y = kwargs.get("y", 0)
            width = kwargs.get("width")
            height = kwargs.get("height")

            if width and height:
                screenshot = pyautogui.screenshot(region=(x, y, width, height))
            else:
                screenshot = pyautogui.screenshot()

            # Encode as base64 PNG
            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")

            return ToolResult(
                success=True,
                output=f"screenshot:{encoded}",
                metadata={
                    "format": "PNG",
                    "base64_length": len(encoded),
                    "dimensions": [screenshot.width, screenshot.height],
                    "region": {"x": x, "y": y, "width": width or screenshot.width,
                               "height": height or screenshot.height},
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Error taking screenshot: {exc}")


class ReadScreenTextTool(MCPTool):
    """
    Attempt to read text content from the screen at given coordinates.
    Uses basic pixel analysis as a fallback; for proper OCR, integrate pytesseract.
    """

    name = "read_screen_text"
    description = (
        "Read text visible on screen at the given (x, y) pixel coordinates. "
        "Returns any text found near the coordinates. Requires Screen Recording permission."
    )
    input_schema: dict[str, Any] = {
        "properties": {
            "x": {"type": "integer", "description": "X coordinate in pixels."},
            "y": {"type": "integer", "description": "Y coordinate in pixels."},
            "width": {"type": "integer", "description": "Width of region to scan (default: 300).", "default": 300},
            "height": {"type": "integer", "description": "Height of region to scan (default: 100).", "default": 100},
        },
        "required": ["x", "y"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import pyautogui  # type: ignore[import-not-found]

            x = int(kwargs.get("x", 0))
            y = int(kwargs.get("y", 0))
            w = int(kwargs.get("width", 300))
            h = int(kwargs.get("height", 100))

            screenshot = pyautogui.screenshot(region=(x, y, w, h))

            # Try to use pytesseract if available
            try:
                import pytesseract  # type: ignore[import-not-found]
                text = pytesseract.image_to_string(screenshot)
                text = text.strip()
                if text:
                    return ToolResult(
                        success=True,
                        output=f"Detected text: '{text}'",
                        metadata={"x": x, "y": y, "width": w, "height": h, "method": "tesseract"},
                    )
            except ImportError:
                pass

            # Fallback: no OCR available
            return ToolResult(
                success=True,
                output="Text reading requires pytesseract (not installed). "
                       "Install with: pip install pytesseract",
                metadata={"x": x, "y": y, "width": w, "height": h, "method": "none"},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Error reading screen text: {exc}")


# ── Tool Registry ──────────────────────────────────────────────


class ToolRegistry:
    """
    Central registry for all MCP tools.

    Google Stitch MCP integration rules:
      • Tools are registered at startup with their JSON schema.
      • The LLM discovers tools via get_tool_schemas().
      • Tool execution is dispatched via call_tool(name, **kwargs).
      • Results are returned as ToolResult objects (success/error/metadata).
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger("Syth.MCP")
        self._tools: dict[str, MCPTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of system function tools."""
        tools: list[MCPTool] = [
            ViewFileTool(),
            ListDirectoryTool(),
            ExecuteCommandTool(),
            GetMousePositionTool(),
            MoveCursorTool(),
            ClickAtTool(),
            ScrollAtTool(),
            TypeTextTool(),
            TakeScreenshotTool(),
            ReadScreenTextTool(),
        ]
        for tool in tools:
            self.register(tool)

    def register(self, tool: MCPTool) -> None:
        """Register a new MCP tool."""
        self._tools[tool.name] = tool
        self._logger.debug(f"Registered MCP tool: {tool.name}")

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry."""
        if name in self._tools:
            del self._tools[name]
            self._logger.debug(f"Unregistered MCP tool: {name}")
            return True
        return False

    def get_tool(self, name: str) -> Optional[MCPTool]:
        """Look up a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return a list of all registered tool names."""
        return list(self._tools.keys())

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """
        Return all tool schemas in OpenAI function-calling format.
        This is what gets sent to the Vision API so the LLM can discover
        and call tools.
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append(self._build_openai_schema(tool))
        return schemas

    def _build_openai_schema(self, tool: MCPTool) -> dict[str, Any]:
        """Build an OpenAI-compatible function schema for a tool."""
        # Use the class attribute schema
        schema = tool.__class__.schema
        # If schema is a property descriptor, evaluate it
        if isinstance(schema, property):
            schema = type(tool).__dict__["schema"].fget(type(tool))

        if callable(schema):
            try:
                schema = schema
            except Exception:
                schema = {}

        # The schema from the class is already in the right format via the @schema property
        if isinstance(schema, dict) and "function" in schema:
            return schema

        # Fallback: build manually
        properties = getattr(type(tool), "input_schema", {})
        props = {}
        reqs: list[str] = []

        # Flatten properties
        if isinstance(properties, dict):
            if "properties" in properties:
                props.update(properties["properties"])
                reqs = properties.get("required", [])
            else:
                for k, v in properties.items():
                    if isinstance(v, dict):
                        props[k] = v
                        if v.get("required"):
                            reqs.append(k)

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": reqs or [],
                },
            },
        }

    def call_tool(self, name: str, **kwargs: Any) -> ToolResult:
        """
        Execute a registered tool by name with the given keyword arguments.
        Returns a ToolResult.
        """
        tool = self._tools.get(name)
        if tool is None:
            result = ToolResult(
                success=False,
                error=f"Tool '{name}' is not registered.",
            )
            self._logger.error(f"Tool call failed: {name}")
            return result

        try:
            self._logger.info(f"Calling MCP tool: {name}({kwargs})")
            result = tool.execute(**kwargs)
            if result.success:
                self._logger.debug(f"Tool '{name}' succeeded: {result.output[:100]}")
            else:
                self._logger.warning(f"Tool '{name}' failed: {result.error}")
            return result
        except Exception as exc:
            self._logger.error(f"Tool '{name}' raised exception: {exc}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"Tool '{name}' raised: {exc}",
            )

    def execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolResult]:
        """
        Execute a list of tool calls (as returned by the LLM).
        Each entry should have 'name' and 'arguments' keys.
        Returns a list of ToolResult objects in the same order.
        """
        results: list[ToolResult] = []
        for call in tool_calls:
            name = call.get("name", call.get("id", ""))
            arguments = call.get("arguments", call.get("input", {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}

            result = self.call_tool(name, **arguments)
            results.append(result)

        return results

    def get_mcp_manifest(self) -> dict[str, Any]:
        """
        Return a full MCP-compatible manifest of all tools.
        This follows the MCP (Model Context Protocol) specification:
        https://spec.modelcontextprotocol.io/
        """
        tools = []
        for tool in self._tools.values():
            properties = getattr(type(tool), "input_schema", {})
            props = {}
            reqs: list[str] = []
            if isinstance(properties, dict):
                if "properties" in properties:
                    props.update(properties["properties"])
                    reqs = properties.get("required", [])
                else:
                    for k, v in properties.items():
                        if isinstance(v, dict):
                            props[k] = v
                            if v.get("required"):
                                reqs.append(k)

            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {
                    "type": "object",
                    "properties": props,
                    "required": reqs or [],
                },
            })

        return {
            "protocolVersion": "2024-11-5.0",
            "capabilities": {"tools": tools},
            "serverInfo": {
                "name": "Syth-mcp-tools",
                "version": "1.0.0",
                "description": "MCP tool server for the syth desktop agent (Made by Viperwraith47)",
            },
        }
