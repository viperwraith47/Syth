#!/usr/bin/env python3
"""
glass_ui.py — Apple Glass UI for Syth.

Implements absolute glassmorphism in Python (PySide6):
  • Completely transparent background panel (you see the blurred desktop
    through it — "absolute glassmorphism")
  • Subtle rim-light border highlights (white gradient 55% → 5%)
  • Native system background blur (vibrancy) via screen capture + blur
  • Depth shadows (layered, soft)
  • Floating glowing orb anchor that follows the mouse cursor or docks
    to the screen edge

Also implements the Viperwraith47 credit footer (R4) — clickable,
opens https://github.com/viperwraith47 in the default browser.

If PySide6 is unavailable, a lightweight tkinter fallback provides a
simplified transparent window with the same credit widget.

Made by Viperwraith47 — https://github.com/viperwraith47
"""

from __future__ import annotations

import logging
import os
import webbrowser
from typing import Any, Optional

# ── PySide6 availability check ─────────────────────────────────

PYSIDE6_AVAILABLE = False
_UI_BACKEND = "none"

try:
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore[import-not-found]
    from PySide6.QtCore import (
        Qt,
        QTimer,
        QRect,
        QPoint,
        QSize,
        Signal,
        QPropertyAnimation,
        QEasingCurve,
        Property as QtProperty,
    )
    from PySide6.QtGui import (
        QPainter,
        QPen,
        QBrush,
        QColor,
        QLinearGradient,
        QRadialGradient,
        QFont,
        QFontMetrics,
        QAction,
        QCursor,
        QDesktopServices,
        QPixmap,
        QImage,
        QScreen,
        QPainterPath,
        QMouseEvent,
        QResizeEvent,
        QShowEvent,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QHBoxLayout,
        QComboBox,
        QStyle,
        QStyleOption,
        QGraphicsDropShadowEffect,
    )
    PYSIDE6_AVAILABLE = True
    _UI_BACKEND = "pyside6"
except ImportError:
    pass

if not PYSIDE6_AVAILABLE:
    try:
        import tkinter as tk  # type: ignore[import-not-found]
        import tkinter.ttk as ttk  # type: ignore[import-not-found]
        _UI_BACKEND = "tkinter"
    except ImportError:
        _UI_BACKEND = "none"

# ── Color Palette (Apple Glass) ────────────────────────────────

class GlassColors:
    """Apple Glass color palette — monochromatic with blue accent."""
    # Orb / accent colors
    BLUE_500 = QColor(66, 133, 244) if PYSIDE6_AVAILABLE else (66, 133, 244)
    BLUE_400 = QColor(66, 133, 244, 180) if PYSIDE6_AVAILABLE else (66, 133, 244, 180)
    BLUE_300 = QColor(66, 133, 244, 120) if PYSIDE6_AVAILABLE else (66, 133, 244, 120)
    BLUE_200 = QColor(66, 133, 244, 60) if PYSIDE6_AVAILABLE else (66, 133, 244, 60)
    BLUE_100 = QColor(66, 133, 244, 30) if PYSIDE6_AVAILABLE else (66, 133, 244, 30)

    # Glass panel
    GLASS_TINT = QColor(255, 255, 255, 18) if PYSIDE6_AVAILABLE else (255, 255, 255, 18)
    RIM_TOP = QColor(255, 255, 255, 140) if PYSIDE6_AVAILABLE else (255, 255, 255, 140)
    RIM_MID = QColor(255, 255, 255, 30) if PYSIDE6_AVAILABLE else (255, 255, 255, 30)
    RIM_BOTTOM = QColor(255, 255, 255, 13) if PYSIDE6_AVAILABLE else (255, 255, 255, 13)
    SHADOW_HARD = QColor(0, 0, 0, 46) if PYSIDE6_AVAILABLE else (0, 0, 0, 46)
    SHADOW_SOFT = QColor(0, 0, 0, 15) if PYSIDE6_AVAILABLE else (0, 0, 0, 15)

    # Text
    TEXT_PRIMARY = QColor(255, 255, 255, 230) if PYSIDE6_AVAILABLE else (255, 255, 255, 230)
    TEXT_SECONDARY = QColor(255, 255, 255, 150) if PYSIDE6_AVAILABLE else (255, 255, 255, 150)
    TEXT_TERTIARY = QColor(255, 255, 255, 90) if PYSIDE6_AVAILABLE else (255, 255, 255, 90)

    # Vibrant backdrop gradient
    BACKDROP_START = QColor(20, 30, 65) if PYSIDE6_AVAILABLE else (20, 30, 65)
    BACKDROP_END = QColor(70, 40, 90) if PYSIDE6_AVAILABLE else (70, 40, 90)

    # Status colors
    STATUS_ACTIVE = QColor(76, 200, 110) if PYSIDE6_AVAILABLE else (76, 200, 110)
    STATUS_IDLE = QColor(100, 100, 120) if PYSIDE6_AVAILABLE else (100, 100, 120)
    STATUS_ERROR = QColor(240, 80, 80) if PYSIDE6_AVAILABLE else (240, 80, 80)


# ── Blur Manager ───────────────────────────────────────────────

class BlurManager:
    """
    Captures the screen region behind a widget and applies a Gaussian
    blur to simulate native macOS vibrancy (NSVisualEffectView).

    Uses PIL/Pillow for the blur computation. Optimized by downscaling
    before blurring and upscaling back.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger("Syth.UI.Blur")
        self._cache: dict[tuple[int, int, int, int], tuple[QPixmap, float]] = {}
        self._cache_ttl = 0.3  # seconds

    def capture_and_blur(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        blur_radius: float = 12.0,
    ) -> Optional[QPixmap]:
        """
        Capture the screen region (x, y, width, height) and return a
        blurred QPixmap suitable for use as a glassmorphism background.

        Returns None if capture or blur fails.
        """
        try:
            import io
            import base64
            import numpy as np
            from PIL import Image, ImageFilter  # type: ignore[import-not-found]

            # Try Qt screen grab first
            screen: Optional[QScreen] = QApplication.primaryScreen()
            if screen is not None:
                pixmap = screen.grabWindow(0, x, y, width, height)
                if not pixmap.isNull():
                    img = pixmap.toImage()
                    pil_img = Image.fromqimage(img)
                else:
                    raise RuntimeError("Qt screen grab returned null pixmap")
            else:
                # Fallback to pyautogui
                import pyautogui  # type: ignore[import-not-found]
                screenshot = pyautogui.screenshot(region=(x, y, width, height))
                pil_img = screenshot

            # Optimize: downscale before blur
            scale = 0.33  # capture at 1/3 resolution then upscale
            small_w = max(1, int(width * scale))
            small_h = max(1, int(height * scale))
            small = pil_img.resize((small_w, small_h), Image.LANCZOS)

            # Apply Gaussian blur
            blurred = small.filter(ImageFilter.GaussianBlur(radius=blur_radius * scale))

            # Upscale back to original size
            final = blurred.resize((width, height), Image.BILINEAR)

            # Convert back to QPixmap
            buffer = io.BytesIO()
            final.save(buffer, format="PNG")
            buffer.seek(0)
            qimg = QImage()
            qimg.load(buffer, "PNG")
            result = QPixmap.fromImage(qimg)

            return result

        except Exception as exc:
            if self._logger:
                self._logger.debug(f"Blur capture failed: {exc}")
            return None


# ── Glass Panel ────────────────────────────────────────────────

class GlassPanel(QWidget):
    """
    A glassmorphism panel widget.

    Features:
      • Completely transparent background (you see the blurred desktop)
      • Subtle rim-light border (white gradient 55% → 5%)
      • Depth shadows (layered, soft)
      • Continuous corner radii
      • Semi-transparent glass tint overlay

    This is the Python equivalent of the Swift LiquidGlassBackground
    component from the Viperwraith47 project initializer.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        corner_radius: float = 20.0,
        blur_radius: float = 12.0,
        width: int = 380,
        height: int = 280,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(parent)
        self._logger = logger or logging.getLogger("Syth.UI.GlassPanel")

        # Glass properties
        self._corner_radius = corner_radius
        self._blur_radius = blur_radius
        self._width = width
        self._height = height
        self._blurred_bg: Optional[QPixmap] = None
        self._blur_manager = BlurManager(logger)

        # Widget attributes for transparency
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # Resize to requested dimensions
        self.resize(width, height)

        # Blur update timer
        self._blur_timer = QTimer(self)
        self._blur_timer.timeout.connect(self._update_blur)
        self._blur_timer.start(250)  # update blur every 250ms

        self._update_blur()

    def _update_blur(self) -> None:
        """Capture and blur the screen region behind this panel."""
        global_pos = self.mapToGlobal(QPoint(0, 0))
        self._blurred_bg = self._blur_manager.capture_and_blur(
            global_pos.x(), global_pos.y(),
            self.width(), self.height(),
            self._blur_radius,
        )
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Trigger blur update on resize."""
        self._update_blur()
        super().resizeEvent(event)

    def moveEvent(self, event: QtCore.QMoveEvent) -> None:
        """Trigger blur update on move."""
        self._update_blur()
        super().moveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the glassmorphism panel."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()
        r = self._corner_radius

        # ── 1. Depth shadow (behind the panel) ───────────────────
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(0, 0, w, h, r, r)

        # Hard shadow (far, large radius)
        shadow_color = GlassColors.SHADOW_HARD
        for offset_x, offset_y, blur_radius, opacity in [
            (0, 12, 24, 0.18),   # main drop shadow
            (0, 1, 2, 0.06),    # subtle inner shadow
        ]:
            painter.save()
            pass  # Qt6: no BlurEvenAtFullDevicePixel render hint
            painter.fillPath(shadow_path, shadow_color)
            painter.setOpacity(opacity)
            # We use a fake shadow by drawing a blurred path offset
            painter.translate(offset_x, offset_y)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shadow_color)
            painter.drawPath(shadow_path)
            painter.restore()

        # ── 2. Blurred background ───────────────────────────────
        if self._blurred_bg and not self._blurred_bg.isNull():
            painter.save()
            # Clip to rounded rect
            clip_path = QPainterPath()
            clip_path.addRoundedRect(0, 0, w, h, r, r)
            painter.setClipPath(clip_path)
            painter.drawPixmap(0, 0, w, h, self._blurred_bg)
            painter.restore()
        else:
            # Fallback: solid dark background
            painter.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(0, 0, w, h, r, r)
            painter.setClipPath(clip_path)
            painter.fillRect(0, 0, w, h, QBrush(GlassColors.BACKDROP_START))
            painter.restore()

        # ── 3. Glass tint overlay (ultra-thin material) ─────────
        tint_path = QPainterPath()
        tint_path.addRoundedRect(0, 0, w, h, r, r)
        painter.fillPath(tint_path, QBrush(GlassColors.GLASS_TINT))

        # ── 4. Rim light (specular highlight border) ────────────
        rim_gradient = QLinearGradient(0, 0, w, h)
        rim_gradient.setColorAt(0.0, QColor(255, 255, 255, 140))   # 55%
        rim_gradient.setColorAt(0.5, QColor(255, 255, 255, 30))   # ~12%
        rim_gradient.setColorAt(1.0, QColor(255, 255, 255, 13))    # 5%
        rim_pen = QPen(QBrush(rim_gradient), 1)
        painter.setPen(rim_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(tint_path)

    def set_size(self, width: int, height: int) -> None:
        """Set the panel size."""
        self._width = width
        self._height = height
        self.resize(width, height)
        self._update_blur()


# ── Control Button (Glass-style) ──────────────────────────────

class GlassButton(QPushButton):
    """A glass-style push button with material-like appearance."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        width: int = 100,
        height: int = 32,
    ):
        super().__init__(text, parent)
        self._width = width
        self._height = height
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._hover = False
        self._pressed = False

        # Mouse tracking for hover effects
        self.setMouseTracking(True)

        # Font
        font = QFont(".AppleSystemUIFont" if sys_platform_darwin() else "Segoe UI", 12, QFont.Weight.DemiBold)
        self.setFont(font)

        # Text color
        self._text_color = GlassColors.TEXT_PRIMARY

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtGui.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the glass button."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        r = h * 0.4  # capsule-style corners, continuous

        # Button background (thin material)
        bg_alpha = 40 if self._hover else 25
        if self._pressed:
            bg_alpha = 55
        bg_color = QColor(255, 255, 255, bg_alpha)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        painter.fillPath(path, QBrush(bg_color))

        # Rim light
        rim_alpha = 0.30 if self._hover else 0.20
        rim_gradient = QLinearGradient(0, 0, w, h)
        rim_gradient.setColorAt(0.0, QColor(255, 255, 255, int(255 * rim_alpha)))
        rim_gradient.setColorAt(1.0, QColor(255, 255, 255, int(255 * rim_alpha * 0.3)))
        painter.setPen(QPen(QBrush(rim_gradient), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Text
        painter.setPen(QPen(self._text_color))
        painter.setFont(self.font())
        painter.drawText(0, 0, w, h, Qt.AlignCenter, self.text())


class GlassToggleButton(QPushButton):
    """A toggle button with glass styling and active state."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        width: int = 100,
        height: int = 32,
    ):
        super().__init__(text, parent)
        self._width = width
        self._height = height
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._hover = False
        self.setMouseTracking(True)

        font = QFont(".AppleSystemUIFont" if sys_platform_darwin() else "Segoe UI", 11, QFont.Weight.Medium)
        self.setFont(font)

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtGui.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        r = h * 0.4

        is_active = self.isChecked()
        base_alpha = 50 if is_active else 30
        if self._hover:
            base_alpha += 15

        # Background
        if is_active:
            bg_color = QColor(GlassColors.BLUE_500.red(), GlassColors.BLUE_500.green(), GlassColors.BLUE_500.blue(), base_alpha)
        else:
            bg_color = QColor(255, 255, 255, base_alpha)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        painter.fillPath(path, QBrush(bg_color))

        # Rim light
        if is_active:
            rim_gradient = QLinearGradient(0, 0, w, h)
            rim_gradient.setColorAt(0.0, QColor(GlassColors.BLUE_500.red(), GlassColors.BLUE_500.green(), GlassColors.BLUE_500.blue(), 180))
            rim_gradient.setColorAt(1.0, QColor(GlassColors.BLUE_500.red(), GlassColors.BLUE_500.green(), GlassColors.BLUE_500.blue(), 60))
            painter.setPen(QPen(QBrush(rim_gradient), 1))
        else:
            rim_alpha = 0.28 if self._hover else 0.20
            rim_gradient = QLinearGradient(0, 0, w, h)
            rim_gradient.setColorAt(0.0, QColor(255, 255, 255, int(255 * rim_alpha)))
            rim_gradient.setColorAt(1.0, QColor(255, 255, 255, int(255 * rim_alpha * 0.3)))
            painter.setPen(QPen(QBrush(rim_gradient), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Text
        text_color = GlassColors.BLUE_500 if is_active else GlassColors.TEXT_PRIMARY
        painter.setPen(QPen(text_color))
        painter.setFont(self.font())
        painter.drawText(0, 0, w, h, Qt.AlignCenter, self.text())


class GlassComboBox(QComboBox):
    """A glass-style combo box for model selection."""

    def __init__(self, parent: Optional[QWidget] = None, width: int = 140, height: int = 32):
        super().__init__(parent)
        self._width = width
        self._height = height
        self.setFixedHeight(height)
        self.setMinimumWidth(width)
        self.setStyleSheet("""
            QComboBox {
                background: rgba(255, 255, 255, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.30);
                border-radius: 16px;
                padding-left: 12px;
                padding-right: 8px;
                color: rgba(255, 255, 255, 230);
                font-family: '.AppleSystemUIFont', sans-serif;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                background: rgba(20, 30, 65, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.30);
                border-radius: 12px;
                selection-background-color: rgba(66, 133, 244, 0.4);
                color: rgba(255, 255, 255, 230);
                outline: none;
            }
            QComboBox::item {
                padding: 6px 12px;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(255, 255, 255, 0.1);
                width: 8px;
                margin: 0;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
        """)
        self.view().setStyleSheet("""
            QListView {
                background: rgba(20, 30, 65, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                outline: none;
                color: rgba(255, 255, 255, 230);
                font-size: 12px;
            }
            QListView::item {
                padding: 6px 12px;
            }
            QListView::item:selected {
                background: rgba(66, 133, 244, 0.4);
            }
        """)


# ── Status Indicator ───────────────────────────────────────────

class StatusIndicator(QWidget):
    """A small glowing dot that indicates the agent's status."""

    def __init__(self, size: int = 10, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._size = size
        self._status = "idle"  # idle, active, error
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(size, size)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cx, cy = w / 2, h / 2
        radius = self._size / 2

        if self._status == "active":
            color = GlassColors.STATUS_ACTIVE
            glow_radius = radius * 2.5
        elif self._status == "error":
            color = GlassColors.STATUS_ERROR
            glow_radius = radius * 2
        else:
            color = GlassColors.STATUS_IDLE
            glow_radius = radius * 1.5

        # Glow (radial gradient)
        glow_gradient = QRadialGradient(cx, cy, glow_radius)
        glow_gradient.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 120))
        glow_gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))

        glow_path = QPainterPath()
        glow_path.addEllipse(QPoint(cx, cy) - QPoint(radius * 2, radius * 2),
                             radius * 4, radius * 4)
        painter.fillPath(glow_path, QBrush(glow_gradient))

        # Core circle
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(cx, cy), radius, radius)


# ── Floating Orb ───────────────────────────────────────────────

class OrbWidget(QWidget):
    """
    A floating, glowing orb that follows the mouse cursor.

    Behavior:
      • Near the screen center: follows the cursor with smooth interpolation.
      • Near a screen edge: docks to that edge with a small offset.
      • Transparent to mouse events (doesn't block desktop interaction).
      • Always on top of other windows.

    This is the "floating glowing orb anchor" from the requirements.
    """

    def __init__(
        self,
        config: Any,
        parent: Optional[QWidget] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(parent)
        self._logger = logger or logging.getLogger("Syth.UI.Orb")
        self._config = config.ui

        # Orb geometry
        self._orb_size = self._config.orb_size
        self._glow_radius = self._config.orb_glow_radius
        self._total_size = self._orb_size + 2 * self._glow_radius

        # Position state
        from utils import get_screen_size
        self._screen_w, self._screen_h = get_screen_size()
        self._orb_x = self._screen_w / 2
        self._orb_y = 100
        self._target_x = self._orb_x
        self._target_y = self._orb_y

        # Widget setup
        self.resize(self._total_size, self._total_size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus | Qt.X11BypassWindowManagerHint
        )
        # Don't start tracking immediately — wait for show
        self._track_timer: Optional[QTimer] = None

    def showEvent(self, event: QShowEvent) -> None:
        """Start the mouse tracking timer when the orb is shown."""
        super().showEvent(event)
        if self._track_timer is None:
            self._track_timer = QTimer(self)
            self._track_timer.timeout.connect(self._track_mouse)
            self._track_timer.start(16)  # ~60 FPS
        self._logger.debug("Orb tracking started")

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        if self._track_timer is not None:
            self._track_timer.stop()
            self._track_timer = None
        super().hideEvent(event)

    def _track_mouse(self) -> None:
        """Poll the global mouse position and update orb target."""
        try:
            cursor = QCursor()
            pos = cursor.pos()
            mx, my = pos.x(), pos.y()

            # Calculate target with docking logic
            self._target_x, self._target_y = self._dock_target(mx, my)

            # Smooth interpolation (critically damped spring)
            speed = self._config.orb_follow_speed
            self._orb_x += (self._target_x - self._orb_x) * speed
            self._orb_y += (self._target_y - self._orb_y) * speed

            # Move widget (centered on the orb core)
            win_x = int(self._orb_x - self._orb_size / 2 - self._glow_radius)
            win_y = int(self._orb_y - self._orb_size / 2 - self._glow_radius)
            self.move(win_x, win_y)

        except Exception as exc:
            if self._logger:
                self._logger.debug(f"Orb tracking error: {exc}")

    def _dock_target(self, mx: float, my: float) -> tuple[float, float]:
        """
        Calculate the target position for the orb.

        If the mouse is near a screen edge, the orb docks to that edge
        instead of following the cursor directly.
        """
        threshold = self._config.dock_threshold
        offset = self._config.orb_size / 2 + self._config.orb_glow_radius + 8

        target_x = mx
        target_y = my

        # Left edge dock
        if mx < threshold:
            target_x = offset
        # Right edge dock
        elif mx > self._screen_w - threshold:
            target_x = self._screen_w - offset

        # Top edge dock
        if my < threshold:
            target_y = offset
        # Bottom edge dock
        elif my > self._screen_h - threshold:
            target_y = self._screen_h - offset

        return (target_x, target_y)

    def set_dock_mode(self, enabled: bool) -> None:
        """Enable or disable orb following."""
        if self._track_timer is not None:
            if enabled:
                self._track_timer.start(16)
            else:
                self._track_timer.stop()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the glowing orb."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        cx = self._total_size / 2
        cy = self._total_size / 2
        core_r = self._orb_size / 2

        # ── Glow (radial gradient — multiple layers) ──────────────
        for i, (radius_mult, opacity) in enumerate([
            (2.5, 0.15),
            (1.8, 0.25),
            (1.2, 0.35),
        ]):
            glow_radius = core_r + self._glow_radius * radius_mult * 0.4
            gradient = QRadialGradient(cx, cy, glow_radius)
            gradient.setColorAt(0.0, QColor(66, 133, 244, int(255 * opacity)))
            gradient.setColorAt(0.7, QColor(66, 133, 244, int(255 * opacity * 0.3)))
            gradient.setColorAt(1.0, QColor(66, 133, 244, 0))
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(cx, cy), glow_radius, glow_radius)

        # ── Core orb ──────────────────────────────────────────────
        core_gradient = QBrush(QRadialGradient(cx, cy, core_r))
        # Actually, use a proper gradient
        core_gradient = QRadialGradient(cx - core_r * 0.3, cy - core_r * 0.3, core_r)
        core_gradient.setColorAt(0.0, QColor(100, 180, 255, 255))
        core_gradient.setColorAt(0.6, QColor(66, 133, 244, 220))
        core_gradient.setColorAt(1.0, QColor(40, 100, 220, 140))
        painter.setBrush(core_gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(cx, cy), core_r, core_r)

        # ── Specular highlight ────────────────────────────────────
        highlight_gradient = QRadialGradient(
            cx - core_r * 0.4, cy - core_r * 0.4, core_r * 0.5
        )
        highlight_gradient.setColorAt(0.0, QColor(255, 255, 255, 160))
        highlight_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(highlight_gradient)
        painter.drawEllipse(
            QPoint(cx - core_r * 0.4, cy - core_r * 0.4),
            core_r * 0.4, core_r * 0.4
        )


# ── Viperwraith47 Credit Widget ─────────────────────────────────

class ViperwraithCreditWidget(QWidget):
    """
    Clickable "Made by Viperwraith47" credit widget.

    Implements R4 from the Viperwraith47 macOS App Project Initializer:
      • Visible "Made by Viperwraith47" text in the footer
      • Click opens default browser to https://github.com/viperwraith47
      • Accessibility label, hint, isLink trait
      • Pointing hand cursor on hover

    This is the Python equivalent of ViperwraithCreditView.swift.
    """

    # Exact URL — MUST NOT be changed (Viperwraith47 requirement)
    PROFILE_URL = "https://github.com/viperwraith47"

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip(f"Open {self.PROFILE_URL} in your browser")
        self._hover = False
        self.setMouseTracking(True)

        # Accessibility
        self.setAccessibleName("Made by Viperwraith47")
        self.setAccessibleDescription("Opens GitHub profile in your browser")

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtGui.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            # Open URL in default browser (NSWorkspace equivalent)
            webbrowser.open(self.PROFILE_URL)
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(QFont(".AppleSystemUIFont" if sys_platform_darwin() else "Segoe UI", 11))
        text_width = fm.horizontalAdvance("Made by Viperwraith47")
        return QSize(text_width + 20, 32)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w = self.width()
        h = self.height()

        # Background (subtle glass highlight on hover)
        if self._hover:
            bg_alpha = 35
        else:
            bg_alpha = 0
        if bg_alpha > 0:
            path = QPainterPath()
            path.addRoundedRect(0, 0, w, h, 8, 8)
            painter.fillPath(path, QBrush(QColor(255, 255, 255, bg_alpha)))

        # Text: "Made by" (light gray)
        painter.setPen(QPen(GlassColors.TEXT_SECONDARY))
        font = QFont(".AppleSystemUIFont" if sys_platform_darwin() else "Segoe UI", 11)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance("Made by")
        painter.drawText(0, h / 2 + 4, "Made by")

        # Link: "Viperwraith47" (blue, underlined on hover)
        link_text = "Viperwraith47"
        link_x = text_w + 6
        painter.save()
        if self._hover:
            painter.setPen(QPen(GlassColors.BLUE_400))
            font.setWeight(QFont.Weight.DemiBold)
            underline_font = font
            underline_font.setUnderline(True)
            painter.setFont(underline_font)
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 200)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
        painter.drawText(link_x, h / 2 + 4, link_text)
        painter.restore()


def sys_platform_darwin() -> bool:
    """Check if running on macOS."""
    import platform
    return platform.system() == "Darwin"


# ── Main Status Panel ──────────────────────────────────────────

class StatusPanel(GlassPanel):
    """
    The main Apple Glass status panel.

    Contains:
      • App title ("Syth")
      • Status indicator (glowing dot)
      • Current model display
      • Stats (iterations, API calls, errors)
      • Start/Stop toggle button
      • Model selector
      • Viperwraith47 credit footer
    """

    def __init__(
        self,
        app_config: Any,
        vision_agent: Any,
        tool_registry: Any,
        logger: Optional[logging.Logger] = None,
        parent: Optional[QWidget] = None,
    ):
        self._logger = logger or logging.getLogger("Syth.UI.StatusPanel")
        self._app_config = app_config
        self._vision_agent = vision_agent
        self._tool_registry = tool_registry

        super().__init__(
            parent=parent,
            corner_radius=24.0,
            blur_radius=12.0,
            width=app_config.ui.panel_width,
            height=app_config.ui.panel_height,
            logger=logger,
        )

        self._setup_ui()
        self._setup_update_timer()

    def _setup_ui(self) -> None:
        """Create and layout all child widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Header: Title + Status ───────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        # App title
        self._title_label = QLabel("Syth")
        title_font = QFont(".AppleSystemUIFont" if sys_platform_darwin() else "Segoe UI", 20, QFont.Weight.DemiBold)
        title_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet("color: rgba(255, 255, 255, 230); background: transparent;")
        header.addWidget(self._title_label)

        header.addStretch()

        # Status indicator
        self._status_indicator = StatusIndicator(size=10)
        header.addWidget(self._status_indicator)

        layout.addLayout(header)

        # ── Model + Stats ────────────────────────────────────────
        self._model_label = QLabel("Model: Llama-3.2-Vision")
        self._model_label.setStyleSheet(
            "color: rgba(255, 255, 255, 150); background: transparent; font-size: 12px;"
        )
        layout.addWidget(self._model_label)

        self._status_label = QLabel("Idle — waiting for vision loop…")
        self._status_label.setStyleSheet(
            "color: rgba(255, 255, 255, 180); background: transparent; font-size: 12px;"
        )
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # Stats
        self._stats_label = QLabel("Iterations: 0 | API calls: 0 | Errors: 0")
        self._stats_label.setStyleSheet(
            "color: rgba(255, 255, 255, 100); background: transparent; font-size: 10px;"
        )
        layout.addWidget(self._stats_label)

        # ── Controls ─────────────────────────────────────────────
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(12)

        self._toggle_button = GlassToggleButton("Start Loop", width=120, height=32)
        controls.addWidget(self._toggle_button)

        self._model_combo = GlassComboBox(width=140, height=32)
        self._populate_model_combo()
        controls.addWidget(self._model_combo)

        controls.addStretch()

        layout.addLayout(controls)

        # ── Permissions warning (conditionally visible) ──────────
        self._perm_warning = QLabel("⚠ Missing macOS permissions")
        self._perm_warning.setStyleSheet(
            "color: rgba(255, 100, 80, 220); background: transparent; font-size: 10px;"
        )
        self._perm_warning.setVisible(False)
        layout.addWidget(self._perm_warning)

        # ── Credit Footer ────────────────────────────────────────
        credit_layout = QHBoxLayout()
        credit_layout.addStretch()
        self._credit = ViperwraithCreditWidget()
        credit_layout.addWidget(self._credit)
        credit_layout.addStretch()
        layout.addLayout(credit_layout)

        # Connect signals
        self._toggle_button.clicked.connect(self._on_toggle_clicked)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)

    def _populate_model_combo(self) -> None:
        """Populate the model selector with available models."""
        from config import AVAILABLE_MODELS
        self._model_combo.clear()
        for slug, info in AVAILABLE_MODELS.items():
            self._model_combo.addItem(info["display_name"], userData=slug)
        # Set current to the active model
        active_slug = self._app_config.vision.default_model
        idx = self._model_combo.findData(active_slug)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)

    def _setup_update_timer(self) -> None:
        """Set up a timer to periodically update the UI from vision agent stats."""
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_ui)
        self._update_timer.start(int(self._app_config.ui.status_update_interval * 1000))

    def _on_toggle_clicked(self) -> None:
        """Handle start/stop button click."""
        if self._vision_agent.is_running:
            self._vision_agent.stop()
            self._toggle_button.setText("Start Loop")
            self._toggle_button.setChecked(False)
        else:
            import threading
            thread = threading.Thread(target=self._vision_agent.run, daemon=True)
            thread.start()
            self._toggle_button.setText("Stop Loop")
            self._toggle_button.setChecked(True)

    def _on_model_changed(self, text: str) -> None:
        """Handle model selection change."""
        slug = self._model_combo.currentData()
        if slug and self._vision_agent.switch_model(slug):
            self._model_label.setText(f"Model: {self._app_config.vision.display_name()}")

    def _update_ui(self) -> None:
        """Update the UI from the vision agent's current stats."""
        try:
            stats = self._vision_agent.get_stats()

            # Status
            if stats.running:
                self._status_indicator.set_status("active")
            elif stats.errors > 0 and not stats.running:
                self._status_indicator.set_status("error")
            else:
                self._status_indicator.set_status("idle")

            self._status_label.setText(stats.status_message)
            self._stats_label.setText(
                f"Iterations: {stats.iterations} | API calls: {stats.api_calls} | "
                f"Tools: {stats.tools_called} | Errors: {stats.errors}"
            )

            # Permissions warning
            has_missing = any(not v for v in stats.permissions.values())
            self._perm_warning.setVisible(has_missing)
            if has_missing:
                missing = [k for k, v in stats.permissions.items() if not v]
                self._perm_warning.setText(
                    f"⚠ Missing: {', '.join(missing)} — grant in System Settings"
                )
        except Exception as exc:
            self._logger.debug(f"UI update error: {exc}")


# ── Main Window ────────────────────────────────────────────────

class AppleGlassWindow(QMainWindow):
    """
    The main application window with Apple Glass UI.

    Features:
      • Frameless, transparent window
      • Vibrant gradient backdrop (blue → purple)
      • Glass panel card with blur + rim light + depth
      • Floating orb (separate widget, follows mouse)
      • Viperwraith47 credit footer
    """

    # Window geometry
    WINDOW_WIDTH = 420
    WINDOW_HEIGHT = 320

    def __init__(
        self,
        app_config: Any,
        vision_agent: Any,
        tool_registry: Any,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__()
        self._logger = logger or logging.getLogger("Syth.UI.Window")
        self._app_config = app_config
        self._vision_agent = vision_agent
        self._tool_registry = tool_registry

        # Window flags: frameless, transparent, always on top
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setWindowOpacity(0.95)  # mostly opaque window, transparent widgets inside

        # Resize to a reasonable size
        self.resize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)

        # Center on screen
        from utils import get_screen_size
        sw, sh = get_screen_size()
        # Position in top-right area
        x = sw - self.WINDOW_WIDTH - 30
        y = 40
        self.move(x, y)

        # ── Main backdrop (vibrant gradient) ─────────────────────
        self._backdrop = QWidget(self)
        self._backdrop.setGeometry(0, 0, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self._backdrop.setAttribute(Qt.WA_TranslucentBackground)

        # ── Glass panel ───────────────────────────────────────────
        self._glass_panel = StatusPanel(
            app_config=app_config,
            vision_agent=vision_agent,
            tool_registry=tool_registry,
            logger=logger,
            parent=self,
        )
        panel_w = app_config.ui.panel_width
        panel_h = app_config.ui.panel_height
        panel_x = (self.WINDOW_WIDTH - panel_w) // 2
        panel_y = (self.WINDOW_HEIGHT - panel_h) // 2
        self._glass_panel.setGeometry(panel_x, panel_y, panel_w, panel_h)

        # ── Floating orb ──────────────────────────────────────────
        self._orb = OrbWidget(
            config=app_config,
            logger=logger,
        )
        self._orb.show()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the vibrant backdrop gradient."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Vibrant gradient backdrop (blue → purple mesh)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(20, 30, 65))    # deep blue
        gradient.setColorAt(0.3, QColor(35, 30, 75))    # blue-purple
        gradient.setColorAt(0.6, QColor(55, 40, 80))    # purple
        gradient.setColorAt(1.0, QColor(70, 40, 90))    # deep purple

        painter.fillRect(self.rect(), QBrush(gradient))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Clean up on window close."""
        if self._orb:
            self._orb.hide()
        if self._vision_agent:
            self._vision_agent.stop()
        super().closeEvent(event)

    def toggle_orb(self, visible: bool) -> None:
        """Show or hide the floating orb."""
        if self._orb:
            if visible:
                self._orb.show()
            else:
                self._orb.hide()

    def show_credits(self) -> None:
        """Open the Viperwraith47 GitHub profile (R4)."""
        import webbrowser
        webbrowser.open(ViperwraithCreditWidget.PROFILE_URL)


# ── Tkinter Fallback (if PySide6 unavailable) ──────────────────

class TkGlassUI:
    """
    Simplified tkinter fallback UI.

    Provides a transparent window with the Viperwraith47 credit.
    Does not support native blur or the floating orb animation, but
    ensures the app is functional.
    """

    def __init__(self, app_config: Any, vision_agent: Any, tool_registry: Any, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger("Syth.UI.Fallback")
        self._app_config = app_config
        self._vision_agent = vision_agent
        self._tool_registry = tool_registry
        self._root: Optional[tk.Tk] = None
        self._label: Optional[tk.Label] = None

    def show(self) -> None:
        """Show the fallback window."""
        self._root = tk.Tk()
        self._root.title("Syth")
        self._root.geometry("360x220")
        self._root.configure(bg="black")

        # Transparent window
        self._root.attributes("-transparentcolor", "black")
        self._root.overrideredirect(True)
        self._root.wm_attributes("-topmost", True)

        # Center window
        self._root.update_idle_tasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = sw - 360 - 30
        y = 40
        self._root.geometry(f"360x220+{x}+{y}")

        # Content
        frame = tk.Frame(self._root, bg="", height=200)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(frame, text="Syth", font=("SF Pro", 22, "bold"),
                 fg="white", bg="").pack(pady=(0, 10))

        self._status_label = tk.Label(frame, text="Syth — Apple Glass UI",
                                       font=("SF Pro", 11), fg="rgba(255,255,255,150)", bg="")
        self._status_label.pack(pady=(0, 10))

        tk.Label(frame, text="Made by", font=("SF Pro", 10),
                 fg="rgba(255,255,255,120)", bg="").pack(pady=(10, 0))

        self._credit_label = tk.Label(
            frame, text="Viperwraith47", font=("SF Pro", 10, "bold"),
            fg="rgba(66,133,244,220)", bg="", cursor="hand2"
        )
        self._credit_label.pack(pady=(0, 0))
        self._credit_label.bind("<Button-1>", self._open_credit)

        # Update timer
        self._update_timer()

    def _open_credit(self, event=None) -> None:
        """Open the Viperwraith47 GitHub profile."""
        import webbrowser
        webbrowser.open("https://github.com/viperwraith47")

    def _update_timer(self) -> None:
        """Update the status label periodically."""
        try:
            stats = self._vision_agent.get_stats()
            self._status_label.config(
                text=f"Model: {stats.current_model} | Iter: {stats.iterations} | "
                     f"API: {stats.api_calls} | Errors: {stats.errors}"
            )
        except Exception:
            pass

        if self._root:
            self._root.after(500, self._update_timer)

    def run(self) -> None:
        """Start the tkinter main loop."""
        if self._root:
            self._root.mainloop()

    def stop(self) -> None:
        """Stop the UI."""
        if self._root:
            self._root.quit()


__all__ = [
    "GlassPanel",
    "StatusPanel",
    "OrbWidget",
    "GlassButton",
    "GlassToggleButton",
    "GlassComboBox",
    "StatusIndicator",
    "ViperwraithCreditWidget",
    "AppleGlassWindow",
    "BlurManager",
    "GlassColors",
    "TkGlassUI",
    "PYSIDE6_AVAILABLE",
    "sys_platform_darwin",
]
