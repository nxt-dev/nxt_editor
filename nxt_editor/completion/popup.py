"""CompletionPopup: the View of the completion MVC.

A frameless, focus-less QListWidget parented to the editor viewport. Being a
plain child widget (not a top level / ToolTip window) gives it reliable
isVisible(), proper repaint on hide, and no focus stealing, so the editor
keeps focus and drives navigation. It is display only: it emits ``accepted``
when an item is chosen and holds no completion logic.
"""
from Qt import QtWidgets
from Qt import QtCore

_STYLE = ('QListWidget { background-color: #232323; color: #d8d8d8;'
          ' border: 1px solid #555; outline: 0; }'
          'QListWidget::item:selected { background-color: #4772b3;'
          ' color: white; }')

_MAX_ROWS = 10
_MAX_ITEMS = 200


class CompletionPopup(QtWidgets.QListWidget):
    """List popup that displays candidates and reports the chosen one."""

    accepted = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(CompletionPopup, self).__init__(parent)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setUniformItemSizes(True)
        self.setStyleSheet(_STYLE)
        self.itemClicked.connect(self._on_item_clicked)
        self.hide()

    def _on_item_clicked(self, item):
        self.accepted.emit(item.text())

    def show_items(self, names, anchor_rect, viewport_height):
        """Display ``names`` anchored under ``anchor_rect`` (the cursor rect).

        :param names: Candidate strings (already filtered/sorted).
        :param anchor_rect: QRect of the text cursor, in viewport coordinates.
        :param viewport_height: Height of the parent viewport, for clamping.
        """
        self.clear()
        self.addItems(list(names)[:_MAX_ITEMS])
        self.setCurrentRow(0)
        row_h = self.sizeHintForRow(0) if self.count() else 16
        rows = min(self.count(), _MAX_ROWS)
        metrics = self.fontMetrics()
        text_w = max(metrics.horizontalAdvance(self.item(i).text())
                     for i in range(self.count()))
        self.setFixedWidth(min(text_w + 30, 400))
        self.setFixedHeight(row_h * rows + 4)
        # Anchor below the cursor; flip above if it would clip the bottom edge.
        x = anchor_rect.left()
        y = anchor_rect.bottom()
        if y + self.height() > viewport_height:
            y = max(0, anchor_rect.top() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()

    def move_selection(self, key):
        """Move the highlighted row for Up/Down/PageUp/PageDown."""
        count = self.count()
        if not count:
            return
        current = self.currentRow()
        if key == QtCore.Qt.Key_Up:
            row = (current - 1) % count
        elif key == QtCore.Qt.Key_Down:
            row = (current + 1) % count
        elif key == QtCore.Qt.Key_PageUp:
            row = max(0, current - _MAX_ROWS)
        else:
            row = min(count - 1, current + _MAX_ROWS)
        self.setCurrentRow(row)

    def current_text(self):
        """Text of the highlighted item (falls back to the first row)."""
        item = self.currentItem()
        if item is None and self.count():
            item = self.item(0)
        return item.text() if item is not None else ''
