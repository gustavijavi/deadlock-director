"""The open sequence plus selection, undo history and file state."""
import os

from PySide6.QtCore import QObject, Signal

from deadlockdirector.sequence import History, Sequence


class Document(QObject):
    changed = Signal()
    selectionChanged = Signal()
    fileChanged = Signal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self.sequence = Sequence()
        self.history = History(self.sequence)
        self.path = None
        self.dirty = False
        self.selection = []  # list of (track name, Keyframe)

    # -- editing ---------------------------------------------------------
    def begin(self):
        """Snapshot for undo. Call before every mutation."""
        self.history.push()

    def commit(self):
        self.dirty = True
        self._pruneSelection()
        self.changed.emit()
        self.fileChanged.emit()

    def addKeyframe(self, track, time, value, select=True):
        self.begin()
        key = self.sequence.track(track).add(time, value)
        if select:
            self.selection = [(track, key)]
            self.selectionChanged.emit()
        self.commit()
        return key

    def deleteSelected(self):
        if not self.selection:
            return
        self.begin()
        for track, key in self.selection:
            self.sequence.track(track).remove(key)
        self.selection = []
        self.selectionChanged.emit()
        self.commit()

    def setBlend(self, blend):
        if not self.selection:
            return
        self.begin()
        for _, key in self.selection:
            key.blend = blend
        self.commit()

    def moveSelected(self, delta):
        """Shift selected keyframes in time (no undo snapshot; caller does it)."""
        for _, key in self.selection:
            key.time = round(max(0.0, key.time + delta), 4)
        for name in {name for name, _ in self.selection}:
            self.sequence.track(name).sort()
        self.dirty = True
        self.changed.emit()

    def undo(self):
        if self.history.undo():
            self._afterHistory()

    def redo(self):
        if self.history.redo():
            self._afterHistory()

    def _afterHistory(self):
        # Keyframe objects were rebuilt, so the old selection is stale.
        self.selection = []
        self.dirty = True
        self.selectionChanged.emit()
        self.changed.emit()
        self.fileChanged.emit()

    # -- selection -------------------------------------------------------
    def select(self, items, add=False):
        items = list(items)
        if add:
            current = list(self.selection)
            for item in items:
                if item in current:
                    current.remove(item)
                else:
                    current.append(item)
            items = current
        self.selection = items
        self.selectionChanged.emit()

    def selectAll(self):
        self.select(list(self.sequence.keyframes()))

    def isSelected(self, track, key):
        return any(k is key for _, k in self.selection)

    def _pruneSelection(self):
        alive = {id(k) for _, k in self.sequence.keyframes()}
        pruned = [(t, k) for t, k in self.selection if id(k) in alive]
        if len(pruned) != len(self.selection):
            self.selection = pruned
            self.selectionChanged.emit()

    # -- files -----------------------------------------------------------
    @property
    def title(self):
        name = os.path.basename(self.path) if self.path else 'Untitled'
        return name + (' *' if self.dirty else '')

    def new(self):
        self.sequence.load_dict(Sequence().to_dict())
        self.history.clear()
        self.path = None
        self.dirty = False
        self.selection = []
        self.selectionChanged.emit()
        self.changed.emit()
        self.fileChanged.emit()

    def load(self, path):
        loaded = Sequence.load(path)
        self.sequence.load_dict(loaded.to_dict())
        self.history.clear()
        self.path = path
        self.dirty = False
        self.selection = []
        self.selectionChanged.emit()
        self.changed.emit()
        self.fileChanged.emit()

    def save(self, path=None):
        path = path or self.path
        self.sequence.save(path)
        self.path = path
        self.dirty = False
        self.fileChanged.emit()

    def touchSettings(self):
        """Sequence-level properties (start tick, name...) were edited."""
        self.dirty = True
        self.changed.emit()
        self.fileChanged.emit()
