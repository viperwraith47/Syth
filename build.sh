#!/usr/bin/env bash
# build.sh — Syth macOS desktop agent build & run
# Made by Viperwraith47 — https://github.com/viperwraith47
set -euo pipefail

APP_NAME="${APP_NAME:-Syth}"
CONFIGURATION="${CONFIGURATION:-Debug}"
OPEN_APP="${OPEN_APP:-1}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "══════════════════════════════════════════════════════════"
echo "  $APP_NAME — macOS Desktop Agent with Apple Glass UI"
echo "  Python $PYTHON_BIN | macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"
echo "  Made by Viperwraith47 → https://github.com/viperwraith47"
echo "══════════════════════════════════════════════════════════"

# ── Detect project root ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python ────────────────────────────────────────────────
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo "✗ Python not found. Install Python 3.11+ from https://python.org"
    exit 1
fi

PY_VERSION=$($PYTHON_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "→ Python $PY_VERSION detected"

# ── Install dependencies ────────────────────────────────────────
echo "→ Installing dependencies from requirements.txt..."
if [ ! -f "requirements.txt" ]; then
    echo "  requirements.txt not found — skipping."
else
    # Upgrade pip
    $PYTHON_BIN -m pip install --upgrade pip --quiet 2>/dev/null || true

    # Install requirements
    if $PYTHON_BIN -m pip install -r requirements.txt --quiet --no-input; then
        echo "  ✓ Dependencies installed."
    else
        echo "  ⚠ Some dependencies failed to install."
        echo "  Run 'pip3 install -r requirements.txt' manually for details."
    fi
fi

# ── Syntax check ───────────────────────────────────────────────
echo "→ Checking Python syntax..."
SYNTAX_OK=1
for f in main.py vision_agent.py mcp_tools.py glass_ui.py config.py utils.py; do
    if [ -f "$f" ]; then
        if ! $PYTHON_BIN -m py_compile "$f" 2>/dev/null; then
            echo "  ✗ Syntax error in $f"
            SYNTAX_OK=0
        fi
    fi
done
if [ "$SYNTAX_OK" -eq 1 ]; then
    echo "  ✓ All Python files pass syntax check."
else
    echo "  ⚠ Syntax errors detected — review before running."
fi

# ── Optionally build .app bundle ────────────────────────────────
if [ -f "setup.py" ] || [ -f "py2app.conf" ]; then
    echo "→ Packaging as .app bundle (py2app)…"
    if $PYTHON_BIN setup.py py2app -O "${CONFIGURATION,,}" 2>/dev/null; then
        APP_PATH="dist/${APP_NAME}.app"
        if [ -d "$APP_PATH" ]; then
            echo "✓ Built: $APP_PATH"
        fi
    else
        echo "  ⚠ py2app build failed — continuing with direct run."
    fi
fi

# ── Run the application ─────────────────────────────────────────
if [ "$OPEN_APP" = "1" ]; then
    echo ""
    echo "→ Launching Syth…"
    echo "  • Apple Glass UI will appear with a floating orb"
    echo "  • Move mouse to top-left corner to stop the vision loop"
    echo "  • Press Ctrl+C in terminal to exit"
    echo "  • Made by Viperwraith47 — https://github.com/viperwraith47"
    echo ""
    $PYTHON_BIN main.py
else
    echo "→ Build complete. Run with: python3 main.py"
    echo "  Or: ./build.sh"
fi

echo ""
echo "Done. Made by Viperwraith47 → https://github.com/viperwraith47"
