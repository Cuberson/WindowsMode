"""Glass material & motion — the port of Glass.swift.

On Windows 11 the frosted-glass look is real: DWM system backdrop (acrylic /
mica) behind a translucent frameless window, rounded corners via
DWMWA_WINDOW_CORNER_PREFERENCE. On Windows 10 we fall back to a painted
semi-opaque dark card with the same hairline border and shadow.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

IS_WINDOWS = sys.platform == "win32"

ACCENT = QColor(0x4C, 0xC2, 0xFF)
TEXT = QColor(0xFF, 0xFF, 0xFF)
SECONDARY = QColor(0xEB, 0xEB, 0xF0, 190)
TERTIARY = QColor(0xEB, 0xEB, 0xF0, 120)
GREEN = QColor(0x6C, 0xCB, 0x5F)
ORANGE = QColor(0xFF, 0xB3, 0x40)
RED = QColor(0xFF, 0x6B, 0x6B)
GRAY = QColor(0x9A, 0x9A, 0xA2)

FONT_FAMILY = "Segoe UI"
ICON_FONT = "Segoe MDL2 Assets"

_backdrop_enabled: Optional[bool] = None


def backdrop_enabled() -> bool:
    global _backdrop_enabled
    if _backdrop_enabled is not None:
        return _backdrop_enabled
    _backdrop_enabled = False
    if not IS_WINDOWS:
        return _backdrop_enabled
    try:
        import ctypes

        dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_TRANSIENTWINDOW = 2     # acrylic
        val = ctypes.c_int(DWMSBT_TRANSIENTWINDOW)
        rc = dwmapi.DwmSetWindowAttribute(
            _dummy_hwnd(), DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(val), ctypes.sizeof(val)
        )
        _backdrop_enabled = rc == 0
    except Exception:
        _backdrop_enabled = False
    return _backdrop_enabled


_dummy: Optional[QWidget] = None


def _dummy_hwnd() -> int:
    global _dummy
    if _dummy is None:
        _dummy = QWidget()
        _dummy.winId()   # force native window creation
    return int(_dummy.winId())


def apply_backdrop(widget: QWidget, acrylic: bool = True) -> bool:
    """Turns on the Win11 system backdrop + rounded corners for a frameless window."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        corner = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                     ctypes.byref(corner), ctypes.sizeof(corner))
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                     ctypes.byref(dark), ctypes.sizeof(dark))
        if acrylic:
            DWMWA_SYSTEMBACKDROP_TYPE = 38
            DWMSBT_TRANSIENTWINDOW = 2   # acrylic
            val = ctypes.c_int(DWMSBT_TRANSIENTWINDOW)
            rc = dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                              ctypes.byref(val), ctypes.sizeof(val))
            return rc == 0
    except Exception:
        return False
    return False


def card_alpha() -> int:
    return 140 if backdrop_enabled() else 238


def reduce_motion() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        SPI_GETCLIENTAREAANIMATION = 0x0048
        val = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(val), 0)
        return val.value == 0
    except Exception:
        return False


def font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def glass_paint(painter: QPainter, rect: QRectF, radius: float = 20,
                fill: Optional[QColor] = None, shadow: bool = True) -> None:
    """Rounded translucent card + hairline top-lit border (§5)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if fill is None:
        fill = QColor(0x1C, 0x1C, 0x22, card_alpha())
    if shadow:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 46))
        painter.drawRoundedRect(rect.adjusted(0, 6, 0, 12), radius, radius)
    painter.setBrush(fill)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, radius, radius)
    # Hairline border: bright at the top, fading down.
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, QColor(255, 255, 255, 115))
    grad.setColorAt(0.5, QColor(255, 255, 255, 13))
    grad.setColorAt(1.0, QColor(255, 255, 255, 13))
    pen = QPen(grad, 1.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.restore()


def spring_animation(target: QWidget, property_name: bytes, duration: int = 250) -> QPropertyAnimation:
    anim = QPropertyAnimation(target, property_name)
    anim.setDuration(duration if not reduce_motion() else 120)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    return anim
