#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import math
import time
from typing import Protocol, cast

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QInputDevice, QNativeGestureEvent, QWheelEvent
from PyQt6.QtWidgets import QScrollBar, QWidget


class TransformPanZoomView(Protocol):
    """Structural API required by TransformPanZoomMixin."""

    def resetTransform(self) -> None: ...
    def viewport(self) -> QWidget | None: ...
    def mapToScene(self, point: QPoint) -> QPointF: ...
    def centerOn(self, pos: QPointF) -> None: ...
    def scale(self, sx: float, sy: float) -> None: ...
    def horizontalScrollBar(self) -> QScrollBar | None: ...
    def verticalScrollBar(self) -> QScrollBar | None: ...


class PanZoomInputMixin:
    """Reusable input parsing/suppression for wheel + native pan/zoom gestures."""

    DEFAULT_TOUCHPAD_WHEEL_SUPPRESSION_SECONDS = 0.12
    _pan_zoom_touchpad_wheel_suppression_seconds: float
    _pan_zoom_suppress_touchpad_wheel_until: float

    def init_pan_zoom_input(
        self, touchpad_wheel_suppression_seconds: float = DEFAULT_TOUCHPAD_WHEEL_SUPPRESSION_SECONDS
    ) -> None:
        """Initialize shared input state."""
        self._pan_zoom_touchpad_wheel_suppression_seconds = touchpad_wheel_suppression_seconds
        self._pan_zoom_suppress_touchpad_wheel_until = 0.0

    def pan_zoom_is_touchpad_event(self, event: QWheelEvent) -> bool:
        """Return True when a wheel event is emitted by a touchpad."""
        device = event.pointingDevice()
        return bool(device and device.type() == QInputDevice.DeviceType.TouchPad)

    def pan_zoom_touchpad_wheel_is_suppressed(self) -> bool:
        """Return whether touchpad wheel handling should currently be suppressed."""
        return time.monotonic() < self._pan_zoom_suppress_touchpad_wheel_until

    def pan_zoom_wheel_pan_delta(self, event: QWheelEvent) -> QPointF:
        """Best-effort pan delta for touchpad wheel events."""
        pixel_delta = event.pixelDelta()
        if not pixel_delta.isNull():
            return QPointF(pixel_delta)
        angle_delta = event.angleDelta()
        return QPointF(float(angle_delta.x() / 8.0), float(angle_delta.y() / 8.0))

    def pan_zoom_wheel_steps(self, event: QWheelEvent) -> float:
        """Return wheel steps from angle delta (120 units per step)."""
        return event.angleDelta().y() / 120.0

    def pan_zoom_native_gesture_event(self, event: QEvent | None) -> QNativeGestureEvent | None:
        """Return native gesture event when applicable."""
        if not event or event.type() != QEvent.Type.NativeGesture:
            return None
        return cast(QNativeGestureEvent, event)

    def pan_zoom_native_zoom_factor(self, event: QNativeGestureEvent) -> float | None:
        """Return multiplicative zoom factor for native zoom gesture."""
        if event.gestureType() != Qt.NativeGestureType.ZoomNativeGesture:
            return None
        return math.exp(event.value())

    def pan_zoom_native_pan_delta(self, event: QNativeGestureEvent) -> QPointF | None:
        """Return pan delta for native pan gesture."""
        if event.gestureType() != Qt.NativeGestureType.PanNativeGesture:
            return None
        return event.delta()

    def pan_zoom_suppress_touchpad_wheel_temporarily(self) -> None:
        """Avoid handling duplicated touchpad wheel events after native gestures."""
        self._pan_zoom_suppress_touchpad_wheel_until = (
            time.monotonic() + self._pan_zoom_touchpad_wheel_suppression_seconds
        )


class TransformPanZoomMixin(PanZoomInputMixin):
    """Transform-based pan/zoom behavior for graphics views."""

    DEFAULT_WHEEL_ZOOM_FACTOR = 1.2
    _pan_zoom_wheel_zoom_factor: float

    def _pan_zoom_view(self) -> TransformPanZoomView:
        """Return self cast to the protocol expected by this mixin."""
        return cast(TransformPanZoomView, self)

    def init_pan_zoom(
        self,
        wheel_zoom_factor: float = DEFAULT_WHEEL_ZOOM_FACTOR,
        touchpad_wheel_suppression_seconds: float = PanZoomInputMixin.DEFAULT_TOUCHPAD_WHEEL_SUPPRESSION_SECONDS,
    ) -> None:
        """Initialize transform pan/zoom state."""
        self._pan_zoom_wheel_zoom_factor = wheel_zoom_factor
        self.init_pan_zoom_input(touchpad_wheel_suppression_seconds=touchpad_wheel_suppression_seconds)

    def pan_zoom_reset_zoom(self, preserve_center: bool = True) -> None:
        """Reset transform; optionally keep current scene center."""
        view = self._pan_zoom_view()
        if not preserve_center:
            view.resetTransform()
            return
        viewport = view.viewport()
        if not viewport:
            view.resetTransform()
            return
        current_center = view.mapToScene(viewport.rect().center())
        view.resetTransform()
        view.centerOn(current_center)

    def pan_zoom_zoom_by_factor(self, factor: float) -> None:
        """Transform zoom by multiplicative factor."""
        if factor <= 0:
            return
        self._pan_zoom_view().scale(factor, factor)

    def pan_zoom_zoom_by_steps(self, steps: float) -> None:
        """Transform zoom using wheel-like step units."""
        if steps == 0:
            return
        self.pan_zoom_zoom_by_factor(self._pan_zoom_wheel_zoom_factor**steps)

    def pan_zoom_pan_by_pixels(self, delta: QPointF) -> None:
        """Pan by pixel delta using scrollbars."""
        view = self._pan_zoom_view()
        horizontal = view.horizontalScrollBar()
        vertical = view.verticalScrollBar()
        if horizontal:
            horizontal.setValue(horizontal.value() - int(round(delta.x())))
        if vertical:
            vertical.setValue(vertical.value() - int(round(delta.y())))

    def pan_zoom_handle_wheel_event(self, event: QWheelEvent, wheel_zooms: bool) -> bool:
        """Handle wheel input for transform-based views."""
        if self.pan_zoom_is_touchpad_event(event):
            if self.pan_zoom_touchpad_wheel_is_suppressed():
                event.accept()
                return True
            delta = self.pan_zoom_wheel_pan_delta(event)
            if not delta.isNull():
                self.pan_zoom_pan_by_pixels(delta)
            event.accept()
            return True
        if not wheel_zooms:
            return False
        steps = self.pan_zoom_wheel_steps(event)
        if steps == 0:
            return False
        self.pan_zoom_zoom_by_steps(steps)
        event.accept()
        return True

    def pan_zoom_handle_native_gesture(self, event: QNativeGestureEvent) -> bool:
        """Handle native pan/zoom gestures for transform-based views."""
        zoom_factor = self.pan_zoom_native_zoom_factor(event)
        if zoom_factor is not None:
            self.pan_zoom_zoom_by_factor(zoom_factor)
            self.pan_zoom_suppress_touchpad_wheel_temporarily()
            event.accept()
            return True
        pan_delta = self.pan_zoom_native_pan_delta(event)
        if pan_delta is not None:
            self.pan_zoom_pan_by_pixels(pan_delta)
            self.pan_zoom_suppress_touchpad_wheel_temporarily()
            event.accept()
            return True
        return False

    def pan_zoom_handle_event(self, event: QEvent | None) -> bool:
        """Handle native gesture events for transform-based views."""
        native_event = self.pan_zoom_native_gesture_event(event)
        if not native_event:
            return False
        return self.pan_zoom_handle_native_gesture(native_event)
