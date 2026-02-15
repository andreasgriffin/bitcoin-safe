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


class PanZoomView(Protocol):
    """Structural API required by PanZoomMixin."""

    def resetTransform(self) -> None: ...
    def viewport(self) -> QWidget | None: ...
    def mapToScene(self, point: QPoint) -> QPointF: ...
    def centerOn(self, pos: QPointF) -> None: ...
    def scale(self, sx: float, sy: float) -> None: ...
    def horizontalScrollBar(self) -> QScrollBar | None: ...
    def verticalScrollBar(self) -> QScrollBar | None: ...


class PanZoomMixin:
    """Reusable pan/zoom behavior for compatible graphics/chart views."""

    DEFAULT_WHEEL_ZOOM_FACTOR = 1.2
    DEFAULT_TOUCHPAD_WHEEL_SUPPRESSION_SECONDS = 0.12
    _pan_zoom_wheel_zoom_factor: float
    _pan_zoom_touchpad_wheel_suppression_seconds: float
    _pan_zoom_suppress_touchpad_wheel_until: float

    def _pan_zoom_view(self) -> PanZoomView:
        """Return self cast to the protocol expected by this mixin."""
        return cast(PanZoomView, self)

    def init_pan_zoom(
        self,
        wheel_zoom_factor: float = DEFAULT_WHEEL_ZOOM_FACTOR,
        touchpad_wheel_suppression_seconds: float = DEFAULT_TOUCHPAD_WHEEL_SUPPRESSION_SECONDS,
    ) -> None:
        """Initialize pan/zoom runtime state."""
        self._pan_zoom_wheel_zoom_factor = wheel_zoom_factor
        self._pan_zoom_touchpad_wheel_suppression_seconds = touchpad_wheel_suppression_seconds
        self._pan_zoom_suppress_touchpad_wheel_until = 0.0

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
        """OS-independent zoom method."""
        if factor <= 0:
            return
        self._pan_zoom_view().scale(factor, factor)

    def pan_zoom_zoom_by_steps(self, steps: float) -> None:
        """OS-independent zoom method using wheel-like steps."""
        if steps == 0:
            return
        base_factor = self._pan_zoom_wheel_zoom_factor
        self.pan_zoom_zoom_by_factor(base_factor**steps)

    def pan_zoom_pan_by_pixels(self, delta: QPointF) -> None:
        """OS-independent pan method."""
        view = self._pan_zoom_view()
        horizontal = view.horizontalScrollBar()
        vertical = view.verticalScrollBar()
        if horizontal:
            horizontal.setValue(horizontal.value() - int(round(delta.x())))
        if vertical:
            vertical.setValue(vertical.value() - int(round(delta.y())))

    def pan_zoom_handle_wheel_event(self, event: QWheelEvent, wheel_zooms: bool) -> bool:
        """Handle wheel input for both mouse-wheel zoom and touchpad pan."""
        if self._is_touchpad_event(event):
            if time.monotonic() < self._pan_zoom_suppress_touchpad_wheel_until:
                event.accept()
                return True
            delta = self._wheel_pan_delta(event)
            if not delta.isNull():
                self.pan_zoom_pan_by_pixels(QPointF(delta))
            event.accept()
            return True

        if not wheel_zooms:
            return False

        delta_y = event.angleDelta().y()
        if delta_y == 0:
            return False
        steps = delta_y / 120.0
        self.pan_zoom_zoom_by_steps(steps)
        event.accept()
        return True

    def pan_zoom_handle_native_gesture(self, event: QNativeGestureEvent) -> bool:
        """Handle native gestures and suppress duplicate touchpad wheel events."""
        if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.pan_zoom_zoom_by_factor(math.exp(event.value()))
            self._suppress_touchpad_wheel_temporarily()
            event.accept()
            return True

        if event.gestureType() == Qt.NativeGestureType.PanNativeGesture:
            self.pan_zoom_pan_by_pixels(event.delta())
            self._suppress_touchpad_wheel_temporarily()
            event.accept()
            return True

        return False

    def pan_zoom_handle_event(self, event: QEvent | None) -> bool:
        """Handle generic Qt events relevant for pan/zoom behavior."""
        if not event or event.type() != QEvent.Type.NativeGesture:
            return False
        return self.pan_zoom_handle_native_gesture(cast(QNativeGestureEvent, event))

    def _is_touchpad_event(self, event: QWheelEvent) -> bool:
        """Return whether wheel event is emitted by a touchpad."""
        device = event.pointingDevice()
        return bool(device and device.type() == QInputDevice.DeviceType.TouchPad)

    def _wheel_pan_delta(self, event: QWheelEvent) -> QPoint:
        """Best-effort pan delta for touchpad wheel events."""
        pixel_delta = event.pixelDelta()
        if not pixel_delta.isNull():
            return pixel_delta
        angle_delta = event.angleDelta()
        return QPoint(int(round(angle_delta.x() / 8.0)), int(round(angle_delta.y() / 8.0)))

    def _suppress_touchpad_wheel_temporarily(self) -> None:
        """Avoid handling duplicated touchpad wheel events after native gestures."""
        self._pan_zoom_suppress_touchpad_wheel_until = (
            time.monotonic() + self._pan_zoom_touchpad_wheel_suppression_seconds
        )
