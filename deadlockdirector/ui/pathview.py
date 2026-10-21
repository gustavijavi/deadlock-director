"""Top-down preview of the camera path (X/Y plane, Z is shown as a label)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from deadlockdirector.ui import theme


class PathView(QWidget):
    keyClicked = Signal(object)  # Keyframe from the position track

    def __init__(self, document, parent=None):
        QWidget.__init__(self, parent)
        self.document = document
        self.document.changed.connect(self.update)
        self.document.selectionChanged.connect(self.update)
        self.time = 0.0
        self.live = None  # CameraState reported by the game
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        self._transform = None

    def setTime(self, t):
        self.time = t
        self.update()

    def setLiveCamera(self, state):
        self.live = state
        self.update()

    def _samples(self):
        sequence = self.document.sequence
        track = sequence.track('position')
        if not track.keyframes:
            return []
        start, end = track.keyframes[0].time, track.keyframes[-1].time
        count = max(2, min(600, int((end - start) * 30) + 2))
        return [track.evaluate(start + (end - start) * i / (count - 1)) for i in range(count)]

    def _fit(self, points):
        margin = 64
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        minX, maxX, minY, maxY = min(xs), max(xs), min(ys), max(ys)
        spanX, spanY = max(maxX - minX, 400.0), max(maxY - minY, 400.0)
        cx, cy = (minX + maxX) / 2, (minY + maxY) / 2
        scale = min((self.width() - margin * 2) / spanX, (self.height() - margin * 2) / spanY)
        ox, oy = self.width() / 2, self.height() / 2
        # Source engine: +X east, +Y north -> screen Y is flipped.
        return lambda x, y: QPointF(ox + (x - cx) * scale, oy - (y - cy) * scale)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#101215'))
        sequence = self.document.sequence
        samples = self._samples()
        keys = sequence.track('position').keyframes
        points = [list(s) for s in samples]
        if self.live is not None:
            points.append(self.live.position)
        current = sequence.evaluate(self.time)
        if 'position' in current:
            points.append(current['position'])
        transform = self._fit(points)
        self._transform = transform

        # grid
        p.setPen(QPen(QColor('#1b1e23'), 1))
        for x in range(0, self.width(), 32):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            p.drawLine(0, y, self.width(), y)

        p.setPen(theme.TEXT_DIM)
        p.drawText(QRectF(10, 6, self.width() - 20, 18), Qt.AlignLeft, 'Camera path · top-down')

        if transform is None:
            p.setPen(theme.TEXT_DIM)
            p.drawText(self.rect(), Qt.AlignCenter,
                       'No camera keyframes yet.\nFly the replay free-cam to a spot and press K (or "Add Keyframe").')
            p.end()
            return

        if len(samples) > 1:
            path = QPainterPath(transform(*samples[0][:2]))
            for s in samples[1:]:
                path.lineTo(transform(*s[:2]))
            p.setPen(QPen(theme.ACCENT_DIM, 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        rotationTrack = sequence.track('rotation')
        for index, key in enumerate(keys):
            pt = transform(key.value[0], key.value[1])
            selected = self.document.isSelected('position', key)
            rotation = rotationTrack.evaluate(key.time)
            if rotation is not None:
                self._drawFrustum(p, pt, rotation[1], QColor(212, 168, 90, 90), 22)
            p.setPen(QPen(QColor('#ffffff') if selected else theme.ACCENT.darker(150), 1.5))
            p.setBrush(QColor('#ffffff') if selected else theme.ACCENT)
            p.drawEllipse(pt, 6, 6)
            p.setPen(theme.TEXT)
            p.drawText(pt + QPointF(9, -8), '{}  z {:.0f}'.format(index + 1, key.value[2]))

        if 'position' in current:
            pt = transform(*current['position'][:2])
            yaw = current['rotation'][1] if 'rotation' in current else None
            if yaw is not None:
                self._drawFrustum(p, pt, yaw, QColor(224, 83, 61, 140), 34)
            p.setPen(QPen(QColor('#ffffff'), 1.5))
            p.setBrush(theme.PLAYHEAD)
            p.drawEllipse(pt, 5, 5)

        if self.live is not None:
            pt = transform(self.live.x, self.live.y)
            self._drawFrustum(p, pt, self.live.yaw, QColor(79, 179, 169, 120), 28)
            p.setPen(QPen(theme.LIVE, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(pt, 8, 8)

        # legend
        y = self.height() - 12
        for color, label in ((theme.ACCENT, 'keyframe'), (theme.PLAYHEAD, 'playhead'), (theme.LIVE, 'in-game camera')):
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(14, y - 4), 4, 4)
            p.setPen(theme.TEXT_DIM)
            p.drawText(QPointF(24, y), label)
            y -= 16
        p.end()

    def _drawFrustum(self, p, pt, yaw, color, length):
        angle = math.radians(yaw)
        spread = math.radians(28)
        left = QPointF(pt.x() + math.cos(angle + spread) * length, pt.y() - math.sin(angle + spread) * length)
        right = QPointF(pt.x() + math.cos(angle - spread) * length, pt.y() - math.sin(angle - spread) * length)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF([pt, left, right]))

    def mousePressEvent(self, event):
        if self._transform is None:
            return
        pos = event.position()
        for key in self.document.sequence.track('position').keyframes:
            pt = self._transform(key.value[0], key.value[1])
            if (pt - pos).manhattanLength() < 12:
                self.keyClicked.emit(key)
                return
