"""Keyframe timeline: a ruler with a playhead plus one row per track."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QWidget

from deadlockdirector import interpolation
from deadlockdirector.sequence import TRACK_ORDER
from deadlockdirector.ui import theme

HEADER = 150
RULER = 26
ROW = 30
KEY_RADIUS = 6
SNAP_PIXELS = 7


def format_time(t):
    minutes = int(t // 60)
    return '{:02d}:{:05.2f}'.format(minutes, t - minutes * 60)


class TimelineWidget(QWidget):
    timeScrubbed = Signal(float)
    addKeyframeRequested = Signal(str, float)

    def __init__(self, document, parent=None):
        QWidget.__init__(self, parent)
        self.document = document
        self.document.changed.connect(self.update)
        self.document.selectionChanged.connect(self.update)
        self.time = 0.0
        self.offset = -0.5        # seconds at the left edge of the track area
        self.scale = 60.0         # pixels per second
        self.drag = None          # 'scrub' | 'keys' | 'band' | 'pan'
        self.dragOrigin = None
        self.dragMoved = False
        self.dragLastTime = 0.0
        self.band = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMinimumHeight(RULER + ROW * len(TRACK_ORDER) + 12)

    # -- coordinate helpers ---------------------------------------------
    def timeToX(self, t):
        return HEADER + (t - self.offset) * self.scale

    def xToTime(self, x):
        return (x - HEADER) / self.scale + self.offset

    def rowRect(self, index):
        return QRectF(HEADER, RULER + index * ROW, self.width() - HEADER, ROW)

    def trackAt(self, y):
        index = int((y - RULER) // ROW)
        if 0 <= index < len(TRACK_ORDER) and y >= RULER:
            return TRACK_ORDER[index]
        return None

    def keyAt(self, pos):
        track = self.trackAt(pos.y())
        if track is None:
            return None
        best, bestDistance = None, KEY_RADIUS + 3
        for key in self.document.sequence.track(track).keyframes:
            distance = abs(self.timeToX(key.time) - pos.x())
            if distance <= bestDistance:
                best, bestDistance = key, distance
        return (track, best) if best is not None else None

    def setTime(self, t):
        self.time = t
        x = self.timeToX(t)
        if self.drag is None and (x < HEADER or x > self.width() - 20):
            self.offset = t - (self.width() - HEADER) * 0.15 / self.scale
        self.update()

    def zoomToFit(self):
        duration = max(5.0, self.document.sequence.duration + 1.0)
        self.scale = max(5.0, (self.width() - HEADER - 30) / duration)
        self.offset = -0.5
        self.update()

    def _snap(self, t, ignore=()):
        """Snap to the playhead / other keyframes when within a few pixels."""
        candidates = [self.time, 0.0]
        for _, key in self.document.sequence.keyframes():
            if not any(key is k for k in ignore):
                candidates.append(key.time)
        for c in candidates:
            if abs(c - t) * self.scale <= SNAP_PIXELS:
                return c
        return t

    # -- painting --------------------------------------------------------
    def _tickStep(self):
        for step in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
            if step * self.scale >= 70:
                return step
        return 600

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme.BACKGROUND)
        sequence = self.document.sequence
        duration = sequence.duration

        # rows
        for i, name in enumerate(TRACK_ORDER):
            rect = self.rowRect(i)
            p.fillRect(rect, theme.SURFACE if i % 2 == 0 else theme.SURFACE_ALT)
        # region beyond the sequence end
        if duration > 0:
            endX = self.timeToX(duration)
            if endX < w:
                p.fillRect(QRectF(max(HEADER, endX), RULER, w - max(HEADER, endX), ROW * len(TRACK_ORDER)), QColor(0, 0, 0, 60))

        # grid + ruler
        step = self._tickStep()
        p.fillRect(QRectF(0, 0, w, RULER), theme.SURFACE)
        start = math.floor(self.offset / step) * step
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        p.setFont(font)
        t = start
        while self.timeToX(t) < w:
            x = self.timeToX(t)
            if x >= HEADER:
                p.setPen(QPen(theme.BORDER, 1))
                p.drawLine(QPointF(x, RULER), QPointF(x, RULER + ROW * len(TRACK_ORDER)))
                p.setPen(QPen(theme.TEXT_DIM, 1))
                p.drawLine(QPointF(x, RULER - 7), QPointF(x, RULER))
                p.drawText(QPointF(x + 3, RULER - 10), format_time(max(0.0, t)) if t >= 0 else '')
                half = self.timeToX(t + step / 2)
                p.drawLine(QPointF(half, RULER - 4), QPointF(half, RULER))
            t += step

        # segments + keyframes
        for i, name in enumerate(TRACK_ORDER):
            rect = self.rowRect(i)
            cy = rect.center().y()
            color = theme.TRACK_COLORS[name]
            keys = sequence.track(name).keyframes
            for a, b in zip(keys, keys[1:]):
                x0, x1 = self.timeToX(a.time), self.timeToX(b.time)
                if x1 < HEADER or x0 > w:
                    continue
                pen = QPen(QColor(color.red(), color.green(), color.blue(), 150), 2)
                if a.blend == 'hold':
                    pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.drawLine(QPointF(max(HEADER, x0), cy), QPointF(x1, cy))
            for key in keys:
                x = self.timeToX(key.time)
                if x < HEADER - KEY_RADIUS or x > w + KEY_RADIUS:
                    continue
                selected = self.document.isSelected(name, key)
                diamond = QPolygonF([QPointF(x, cy - KEY_RADIUS - 1), QPointF(x + KEY_RADIUS, cy),
                                     QPointF(x, cy + KEY_RADIUS + 1), QPointF(x - KEY_RADIUS, cy)])
                p.setPen(QPen(QColor('#ffffff') if selected else color.darker(160), 1.5))
                p.setBrush(QBrush(QColor('#ffffff') if selected else color))
                p.drawPolygon(diamond)

        # rubber band
        if self.band is not None:
            p.setPen(QPen(theme.ACCENT, 1, Qt.DashLine))
            p.setBrush(QColor(212, 168, 90, 40))
            p.drawRect(self.band)

        # header column
        p.fillRect(QRectF(0, 0, HEADER, h), theme.SURFACE)
        p.setPen(QPen(theme.BORDER, 1))
        p.drawLine(QPointF(HEADER, 0), QPointF(HEADER, h))
        p.drawLine(QPointF(0, RULER), QPointF(w, RULER))
        p.setFont(self.font())
        for i, name in enumerate(TRACK_ORDER):
            rect = self.rowRect(i)
            track = sequence.track(name)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.TRACK_COLORS[name])
            p.drawRoundedRect(QRectF(10, rect.center().y() - 5, 10, 10), 2, 2)
            p.setPen(theme.TEXT if track.keyframes else theme.TEXT_DIM)
            p.drawText(QRectF(28, rect.top(), HEADER - 34, ROW), Qt.AlignVCenter | Qt.AlignLeft, track.label)
            p.setPen(QPen(theme.BORDER, 1))
            p.drawLine(QPointF(0, rect.bottom()), QPointF(w, rect.bottom()))
        p.setPen(theme.ACCENT)
        p.drawText(QRectF(10, 0, HEADER - 14, RULER), Qt.AlignVCenter | Qt.AlignLeft, format_time(self.time))

        # playhead
        x = self.timeToX(self.time)
        if x >= HEADER:
            p.setPen(QPen(theme.PLAYHEAD, 1.5))
            p.drawLine(QPointF(x, RULER - 2), QPointF(x, RULER + ROW * len(TRACK_ORDER)))
            p.setBrush(theme.PLAYHEAD)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(x - 6, 2), QPointF(x + 6, 2), QPointF(x + 6, RULER - 10), QPointF(x, RULER - 3), QPointF(x - 6, RULER - 10)]))
        p.end()

    # -- interaction -----------------------------------------------------
    def mousePressEvent(self, event):
        pos = event.position()
        if event.button() == Qt.MiddleButton:
            self.drag, self.dragOrigin = 'pan', (pos.x(), self.offset)
            return
        if pos.x() < HEADER:
            return
        if event.button() == Qt.RightButton:
            self._contextMenu(event)
            return
        if event.button() != Qt.LeftButton:
            return
        if pos.y() < RULER:
            self.drag = 'scrub'
            self.timeScrubbed.emit(max(0.0, self.xToTime(pos.x())))
            return
        hit = self.keyAt(pos)
        additive = bool(event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier))
        if hit:
            if additive:
                self.document.select([hit], add=True)
            elif not self.document.isSelected(*hit):
                self.document.select([hit])
            self.drag = 'keys'
            self.dragMoved = False
            self.dragOrigin = pos
            self.dragLastTime = hit[1].time
            self.dragAnchor = hit[1]
        else:
            if not additive:
                self.document.select([])
            self.drag = 'band'
            self.dragOrigin = pos
            self.band = QRectF(pos, pos)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.drag == 'scrub':
            t = max(0.0, self.xToTime(pos.x()))
            self.timeScrubbed.emit(self._snap(t) if not event.modifiers() & Qt.AltModifier else t)
        elif self.drag == 'pan':
            x0, offset = self.dragOrigin
            self.offset = offset - (pos.x() - x0) / self.scale
            self.update()
        elif self.drag == 'keys':
            if not self.dragMoved and abs(pos.x() - self.dragOrigin.x()) < 3:
                return
            if not self.dragMoved:
                self.document.begin()
                self.dragMoved = True
            target = max(0.0, self.xToTime(pos.x()))
            if not event.modifiers() & Qt.AltModifier:
                target = self._snap(target, ignore=[k for _, k in self.document.selection])
            earliest = min(k.time for _, k in self.document.selection)
            delta = max(target - self.dragAnchor.time, -earliest)
            if delta:
                self.document.moveSelected(delta)
        elif self.drag == 'band':
            self.band = QRectF(self.dragOrigin, pos).normalized()
            self.update()
        else:
            hit = self.keyAt(pos) if pos.x() >= HEADER else None
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            if hit:
                track, key = hit
                value = key.value
                if isinstance(value, list):
                    value = ', '.join('{:.1f}'.format(v) for v in value)
                else:
                    value = '{:.3f}'.format(value)
                self.setToolTip('{}\n{}  ·  {}\n{}'.format(self.document.sequence.track(track).label,
                                                           format_time(key.time), key.blend, value))
            else:
                self.setToolTip('')

    def mouseReleaseEvent(self, event):
        if self.drag == 'keys' and self.dragMoved:
            self.document.commit()
        elif self.drag == 'band' and self.band is not None:
            t0, t1 = self.xToTime(self.band.left()), self.xToTime(self.band.right())
            items = []
            for i, name in enumerate(TRACK_ORDER):
                if self.band.intersects(self.rowRect(i)):
                    items += [(name, k) for k in self.document.sequence.track(name).keyframes if t0 <= k.time <= t1]
            if items:
                self.document.select(items, add=bool(event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)))
            self.band = None
            self.update()
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        pos = event.position()
        if pos.x() < HEADER or pos.y() < RULER:
            return
        hit = self.keyAt(pos)
        if hit:
            self.timeScrubbed.emit(hit[1].time)
            return
        track = self.trackAt(pos.y())
        if track:
            self.addKeyframeRequested.emit(track, round(max(0.0, self.xToTime(pos.x())), 3))

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if event.modifiers() & Qt.ControlModifier:
            anchor = self.xToTime(event.position().x())
            factor = 1.15 if delta > 0 else 1 / 1.15
            self.scale = max(2.0, min(2000.0, self.scale * factor))
            self.offset = anchor - (event.position().x() - HEADER) / self.scale
        else:
            self.offset -= delta / 120.0 * 60.0 / self.scale
        self.update()

    def _contextMenu(self, event):
        pos = event.position()
        hit = self.keyAt(pos)
        menu = QMenu(self)
        if hit:
            if not self.document.isSelected(*hit):
                self.document.select([hit])
            blendMenu = menu.addMenu('Blend to next keyframe')
            current = {k.blend for _, k in self.document.selection}
            for name, label in interpolation.BLEND_MODES:
                action = QAction(label, blendMenu, checkable=True)
                action.setChecked(current == {name})
                action.triggered.connect(lambda checked=False, n=name: self.document.setBlend(n))
                blendMenu.addAction(action)
            menu.addAction('Move playhead here', lambda: self.timeScrubbed.emit(hit[1].time))
            menu.addSeparator()
            menu.addAction('Delete', self.document.deleteSelected)
        else:
            track = self.trackAt(pos.y())
            t = round(max(0.0, self.xToTime(pos.x())), 3)
            if track:
                menu.addAction('Add keyframe here', lambda: self.addKeyframeRequested.emit(track, t))
            menu.addAction('Move playhead here', lambda: self.timeScrubbed.emit(t))
            menu.addAction('Zoom to fit', self.zoomToFit)
        menu.exec(event.globalPosition().toPoint())
