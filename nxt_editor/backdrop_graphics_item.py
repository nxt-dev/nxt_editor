"""The picture of a backdrop in the graph view.

The item only draws. Moving, resizing, selecting and editing a backdrop
is done by the view, see StageView.backdrop_press, since moving one moves
nodes the item knows nothing about.

Only the header and the resize corner take the mouse. A click anywhere
else inside a backdrop goes to whatever is under it, the graph included,
so a rubber band can be started inside one.
"""
# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
from nxt_editor import backdrops
from nxt_editor import color_range, colors, theme
from nxt_editor.layer_color_dialog import LayerColorDialog
from nxt_editor.constants import FONTS


class BackdropGraphicsItem(QtWidgets.QGraphicsItem):

    PADDING = 10
    NOTE_GAP = 4
    ROUND = 4.
    HANDLE_SIZE = 16
    BODY_ALPHA = 70
    HEADER_ALPHA = 200

    def __init__(self, backdrop_id, record):
        super(BackdropGraphicsItem, self).__init__()
        self.backdrop_id = backdrop_id
        self.record = None
        self.selected = False
        self.title_font = FONTS.default_font(18)
        self.title_font.setBold(True)
        self.note_font = FONTS.default_font(12)
        self.setAcceptHoverEvents(True)
        self.set_record(record)

    # Geometry -------------------------------------------------------------

    @property
    def width(self):
        return self.record[backdrops.SIZE][0]

    @property
    def height(self):
        return self.record[backdrops.SIZE][1]

    def set_record(self, record):
        self.prepareGeometryChange()
        self.record = backdrops.clean(record)
        self.setPos(*self.record[backdrops.POS])
        self.setToolTip(self.record[backdrops.NOTE])
        self.update()

    def set_size(self, width, height):
        """Resize while dragging, before anything is saved."""
        self.prepareGeometryChange()
        self.record[backdrops.SIZE] = [max(width, backdrops.MIN_SIZE[0]),
                                       max(height, backdrops.MIN_SIZE[1])]
        self.update()

    def boundingRect(self):
        return QtCore.QRectF(-1, -1, self.width + 2, self.height + 2)

    def scene_rect(self):
        return QtCore.QRectF(self.scenePos(),
                             QtCore.QSizeF(self.width, self.height))

    def _text_width(self):
        return max(self.width - (self.PADDING * 2), 10)

    def _title_rect(self):
        metrics = QtGui.QFontMetricsF(self.title_font)
        return QtCore.QRectF(self.PADDING, self.PADDING, self._text_width(),
                             metrics.height())

    def _note_rect(self):
        note = self.record[backdrops.NOTE]
        top = self._title_rect().bottom() + self.NOTE_GAP
        if not note:
            return QtCore.QRectF(self.PADDING, top, self._text_width(), 0)
        metrics = QtGui.QFontMetricsF(self.note_font)
        bounds = metrics.boundingRect(
            QtCore.QRectF(0, 0, self._text_width(), 100000),
            QtCore.Qt.TextWordWrap, note)
        return QtCore.QRectF(self.PADDING, top, self._text_width(),
                             bounds.height())

    def header_rect(self):
        """The title and the note, which is where the backdrop is grabbed."""
        bottom = self._title_rect().bottom()
        if self.record[backdrops.NOTE]:
            bottom = self._note_rect().bottom()
        height = min(bottom + self.PADDING, self.height)
        return QtCore.QRectF(0, 0, self.width, height)

    def handle_rect(self):
        size = self.HANDLE_SIZE
        return QtCore.QRectF(self.width - size, self.height - size,
                             size, size)

    def shape(self):
        path = QtGui.QPainterPath()
        path.addRect(self.header_rect())
        path.addRect(self.handle_rect())
        return path

    def part_at(self, scene_pos):
        """'resize', 'header' or None, for a point in the scene."""
        local = self.mapFromScene(scene_pos)
        if self.handle_rect().contains(local):
            return 'resize'
        if self.header_rect().contains(local):
            return 'header'
        return None

    # Drawing --------------------------------------------------------------

    def color(self):
        color = QtGui.QColor(self.record[backdrops.COLOR])
        if not color.isValid():
            color = QtGui.QColor(backdrops.DEFAULT_COLOR)
        # One saved lighter, before colors were kept to the range white
        # text reads on, shows as the nearest that is.
        return color_range.shown(color)

    def paint(self, painter, option, widget):
        painter.setRenderHints(QtGui.QPainter.Antialiasing |
                               QtGui.QPainter.TextAntialiasing)
        color = self.color()
        rect = QtCore.QRectF(0, 0, self.width, self.height)

        body = QtGui.QColor(color)
        body.setAlpha(self.BODY_ALPHA)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(body)
        painter.drawRoundedRect(rect, self.ROUND, self.ROUND)

        header = QtGui.QColor(color)
        header.setAlpha(self.HEADER_ALPHA)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(rect, self.ROUND, self.ROUND)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(self.header_rect(), header)
        painter.restore()

        if self.selected:
            pen = QtGui.QPen(colors.SELECTED, 2)
        else:
            pen = QtGui.QPen(color.lighter(150), 1)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(rect, self.ROUND, self.ROUND)

        lod = QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(
            painter.worldTransform())
        painter.save()
        painter.setClipRect(self.header_rect())
        painter.setPen(QtGui.QColor(235, 235, 235))
        painter.setFont(self.title_font)
        flags = QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop
        title = QtGui.QFontMetrics(self.title_font).elidedText(
            self.record[backdrops.TITLE], QtCore.Qt.ElideRight,
            int(self._text_width()))
        painter.drawText(self._title_rect(), flags, title)
        note = self.record[backdrops.NOTE]
        if note and lod > .25:
            painter.setPen(QtGui.QColor(225, 225, 225, 210))
            painter.setFont(self.note_font)
            painter.drawText(self._note_rect(),
                             flags | QtCore.Qt.TextWordWrap, note)
        painter.restore()

        # Resize grip, three short diagonals in the corner.
        grip = QtGui.QColor(color.lighter(180))
        grip.setAlpha(160)
        painter.setPen(QtGui.QPen(grip, 1.5))
        right = self.width - 3
        bottom = self.height - 3
        for offset in (4, 8, 12):
            painter.drawLine(QtCore.QPointF(right - offset, bottom),
                             QtCore.QPointF(right, bottom - offset))

    # Mouse ----------------------------------------------------------------

    def hoverMoveEvent(self, event):
        if self.handle_rect().contains(event.pos()):
            self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else:
            self.setCursor(QtCore.Qt.SizeAllCursor)
        super(BackdropGraphicsItem, self).hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super(BackdropGraphicsItem, self).hoverLeaveEvent(event)


class BackdropEditDialog(QtWidgets.QDialog):
    """Title, note and color of one backdrop."""

    SWATCH = 22

    def __init__(self, record, parent=None):
        super(BackdropEditDialog, self).__init__(parent)
        self.setWindowTitle('Edit Backdrop')
        self.setMinimumWidth(380)
        self.color = record[backdrops.COLOR]
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(self.section('Title', first=True))
        self.title_edit = QtWidgets.QLineEdit(record[backdrops.TITLE])
        layout.addWidget(self.title_edit)

        layout.addWidget(self.section('Note'))
        self.note_edit = QtWidgets.QPlainTextEdit(record[backdrops.NOTE])
        self.note_edit.setPlaceholderText(
            'Shown under the title, at the top left of the backdrop.')
        self.note_edit.setTabChangesFocus(True)
        layout.addWidget(self.note_edit)

        layout.addWidget(self.section('Color'))
        swatches = QtWidgets.QHBoxLayout()
        swatches.setSpacing(4)
        self.swatch_buttons = []
        for name, hex_color in backdrops.PRESET_COLORS:
            button = QtWidgets.QToolButton()
            button.setToolTip(name)
            button.setFixedSize(self.SWATCH, self.SWATCH)
            button.setCheckable(True)
            button.setProperty('hex', hex_color)
            button.clicked.connect(
                lambda _=False, c=hex_color: self.set_color(c))
            swatches.addWidget(button)
            self.swatch_buttons += [button]
        self.custom_button = QtWidgets.QToolButton()
        self.custom_button.setText('Custom...')
        self.custom_button.clicked.connect(self.pick_color)
        swatches.addWidget(self.custom_button)
        swatches.addStretch()
        layout.addLayout(swatches)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.set_color(self.color)
        self.title_edit.selectAll()
        self.title_edit.setFocus()

    @staticmethod
    def section(text, first=False):
        """A header starting a section of the dialog.

        The editor's style sheet borders labels just like it borders line
        edits, so a plain label reads as one more field. A header has no
        box, is bold and uppercase, and has room above it.
        """
        label = QtWidgets.QLabel(text.upper())
        top = 0 if first else 10
        label.setStyleSheet(
            'QLabel {{ border: none; background: transparent; '
            'padding: {}px 0px 2px 0px; font-weight: bold; '
            'letter-spacing: 1px; color: {}; }}'.format(
                top, colors.LIGHTEST_TEXT.name()))
        return label

    def set_color(self, hex_color):
        self.color = hex_color
        for button in self.swatch_buttons:
            swatch = button.property('hex')
            chosen = swatch.lower() == hex_color.lower()
            button.setChecked(chosen)
            border = '2px solid {}'.format(colors.SELECTED.name()) \
                if chosen else '1px solid #222'
            button.setStyleSheet(
                'QToolButton {{ background-color: {}; border: {}; }}'.format(
                    swatch, border))
        custom = not any(b.isChecked() for b in self.swatch_buttons)
        style = ''
        if custom:
            style = ('QToolButton {{ background-color: {}; '
                     'border: 2px solid {}; }}'.format(
                         hex_color, colors.SELECTED.name()))
        self.custom_button.setStyleSheet(style)

    def pick_color(self):
        # The same colors as layers, ones white text reads on.
        color = LayerColorDialog.get_color(self.color, self,
                                           title='Backdrop Color')
        if color:
            self.set_color(color)

    def values(self):
        """{title, note, color} as the dialog has them now."""
        return {backdrops.TITLE: self.title_edit.text().strip() or
                backdrops.DEFAULT_TITLE,
                backdrops.NOTE: self.note_edit.toPlainText().rstrip(),
                backdrops.COLOR: self.color}
