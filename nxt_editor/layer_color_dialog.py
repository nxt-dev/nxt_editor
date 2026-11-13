"""Picking a layer's, or a backdrop's, color: any color at all.

The layer is given exactly the color picked. How it is then shown is the
user's own view, see color_range: as it is by default, or darker when too
light for white text, or evened out. In your view shows how the color
picked will look to you.
"""
# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
from nxt_editor import color_range, colors, theme


def shade_color(hue, saturation, shade):
    """The color at a hue, saturation and shade, 0 black and 1 the hue at
    its brightest.

    :rtype: QtGui.QColor
    """
    return QtGui.QColor.fromHsvF(hue, saturation,
                                 min(max(shade, 0.0), 1.0))


def hue_saturation_shade(value):
    """Where a color sits in the picker: its hue, saturation and shade.

    :rtype: (float, float, float)
    """
    hue, saturation, shade, _ = QtGui.QColor(value).getHsvF()
    return max(hue, 0.0), saturation, shade


class HueSaturationField(QtWidgets.QWidget):
    """Hue across, saturation down, each at its lightest safe shade."""
    picked = QtCore.Signal(float, float)
    # Worked out on a coarse grid and smoothed up: every point is a
    # search, and the field only has to show the range.
    GRID = (72, 24)
    _image = None

    def __init__(self, parent=None):
        super(HueSaturationField, self).__init__(parent)
        self.setMinimumSize(288, 120)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.hue = 0.0
        self.saturation = 1.0

    @classmethod
    def image(cls):
        if cls._image is None:
            width, height = cls.GRID
            image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
            for x in range(width):
                hue = x / float(width - 1)
                for y in range(height):
                    saturation = 1.0 - y / float(height - 1)
                    image.setPixel(x, y, shade_color(hue, saturation,
                                                     1.0).rgb())
            cls._image = image
        return cls._image

    def set_position(self, hue, saturation):
        self.hue, self.saturation = hue, saturation
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self.image())
        x = self.hue * (self.width() - 1)
        y = (1.0 - self.saturation) * (self.height() - 1)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 3))
        painter.drawEllipse(QtCore.QPointF(x, y), 5, 5)
        painter.setPen(QtGui.QPen(QtCore.Qt.white, 1.5))
        painter.drawEllipse(QtCore.QPointF(x, y), 5, 5)

    def pick(self, pos):
        hue = min(max(pos.x() / float(max(self.width() - 1, 1)), 0.0), 1.0)
        saturation = 1.0 - min(max(
            pos.y() / float(max(self.height() - 1, 1)), 0.0), 1.0)
        self.set_position(hue, saturation)
        self.picked.emit(hue, saturation)

    def mousePressEvent(self, event):
        self.pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self.pick(event.pos())


class ShadeBar(QtWidgets.QWidget):
    """From the darkest shade offered, at the bottom, to the lightest white
    text reads on, at the top."""
    picked = QtCore.Signal(float)

    def __init__(self, parent=None):
        super(ShadeBar, self).__init__(parent)
        self.setFixedWidth(24)
        self.setMinimumHeight(120)
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self.hue = 0.0
        self.saturation = 1.0
        self.shade = 1.0

    def set_color(self, hue, saturation, shade):
        self.hue, self.saturation, self.shade = hue, saturation, shade
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        rect = self.rect().adjusted(4, 0, -4, 0)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for stop in (0.0, 0.25, 0.5, 0.75, 1.0):
            gradient.setColorAt(stop, shade_color(self.hue, self.saturation,
                                                  1.0 - stop))
        painter.fillRect(rect, gradient)
        y = (1.0 - self.shade) * (self.height() - 1)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 3))
        painter.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(self.width(), y))
        painter.setPen(QtGui.QPen(QtCore.Qt.white, 1.5))
        painter.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(self.width(), y))

    def pick(self, pos):
        shade = 1.0 - min(max(pos.y() / float(max(self.height() - 1, 1)),
                              0.0), 1.0)
        self.shade = shade
        self.update()
        self.picked.emit(shade)

    def mousePressEvent(self, event):
        self.pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self.pick(event.pos())


class Preview(QtWidgets.QWidget):
    """The color, with white text on it as a node shows it."""

    def __init__(self, parent=None):
        super(Preview, self).__init__(parent)
        self.setMinimumSize(120, 32)
        self.color = QtGui.QColor(colors.LAYER_COLORS[0])
        self.label = 'Layer'

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1),
                            theme.NODE_RADIUS, theme.NODE_RADIUS)
        painter.fillPath(path, self.color)
        painter.setPen(theme.color(theme.NODE_TEXT))
        painter.setFont(theme.font(theme.NODE_TITLE_PX))
        painter.drawText(self.rect().adjusted(12, 0, 0, 0),
                         QtCore.Qt.AlignVCenter, self.label)


class LayerColorDialog(QtWidgets.QDialog):
    """Pick a layer's color, any color."""

    def __init__(self, color=None, parent=None, title='Layer Color'):
        super(LayerColorDialog, self).__init__(parent)
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        # The palette.
        swatches = QtWidgets.QGridLayout()
        swatches.setSpacing(4)
        self.swatches = []
        per_row = 8
        for i, swatch_color in enumerate(colors.LAYER_COLORS):
            button = QtWidgets.QPushButton()
            button.setFixedSize(28, 22)
            button.setToolTip(swatch_color.name())
            button.setStyleSheet(
                'QPushButton { background-color: %s; border: none; '
                'border-radius: 3px; } QPushButton:hover { border: 1px '
                'solid %s; }' % (swatch_color.name(), theme.HOVERED))
            button.clicked.connect(
                lambda checked=False, c=swatch_color: self.set_color(c))
            swatches.addWidget(button, i // per_row, i % per_row)
            self.swatches.append(button)
        layout.addLayout(swatches)
        # Any hue and saturation, and a shade.
        pickers = QtWidgets.QHBoxLayout()
        self.field = HueSaturationField(self)
        self.field.picked.connect(self.on_field_picked)
        pickers.addWidget(self.field, 1)
        self.shade_bar = ShadeBar(self)
        self.shade_bar.picked.connect(self.on_shade_picked)
        pickers.addWidget(self.shade_bar)
        layout.addLayout(pickers, 1)
        # What it looks like, and its hex.
        bottom = QtWidgets.QHBoxLayout()
        self.preview = Preview(self)
        bottom.addWidget(self.preview, 1)
        # How this color will look to you in your Layer Color View, which
        # may show it darker or evener. It is not what is stored, see
        # color_range.
        self.view_preview = Preview(self)
        self.view_preview.setFixedWidth(110)
        self.view_preview.label = 'In your view'
        self.view_preview.setToolTip(
            'How this color looks in your Layer Color View, View > Options. '
            'The layer is given the color on the left.')
        bottom.addWidget(self.view_preview)
        self.hex_edit = QtWidgets.QLineEdit()
        self.hex_edit.setFixedWidth(90)
        self.hex_edit.setToolTip('A hex color, any color at all.')
        self.hex_edit.editingFinished.connect(self.on_hex_edited)
        bottom.addWidget(self.hex_edit)
        layout.addLayout(bottom)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.hue, self.saturation, self.shade = 0.0, 1.0, 1.0
        self.set_color(color or colors.LAYER_COLORS[0])

    @property
    def color(self):
        """The color picked.

        :rtype: QtGui.QColor
        """
        return shade_color(self.hue, self.saturation, self.shade)

    def set_color(self, value):
        """Show value."""
        hue, saturation, shade = hue_saturation_shade(value)
        self.hue, self.saturation, self.shade = hue, saturation, shade
        self.field.set_position(hue, saturation)
        self.shade_bar.set_color(hue, saturation, shade)
        self.show_color()

    def show_color(self):
        color = self.color
        self.preview.color = color
        self.preview.update()
        self.view_preview.color = color_range.shown(color)
        self.view_preview.update()
        self.hex_edit.setText(color.name())

    def on_field_picked(self, hue, saturation):
        self.hue, self.saturation = hue, saturation
        self.shade_bar.set_color(hue, saturation, self.shade)
        self.show_color()

    def on_shade_picked(self, shade):
        self.shade = shade
        self.show_color()

    def on_hex_edited(self):
        value = QtGui.QColor(self.hex_edit.text().strip())
        if value.isValid():
            self.set_color(value)
        else:
            self.show_color()

    @classmethod
    def get_color(cls, color=None, parent=None, title='Layer Color'):
        """Ask for a layer's, or a backdrop's, color.

        :return: the color's hex, or None when cancelled
        :rtype: str or None
        """
        dialog = cls(color, parent, title)
        if dialog.exec_():
            return dialog.color.name()
        return None
