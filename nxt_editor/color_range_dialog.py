"""View > Options > Layer Color View: how layer colors are shown to you.

A view preference only. It changes how layer and backdrop colors look to
the user who sets it, never the colors layers are given; Change Color does
that.

White-text safe, the default, or Even, every hue at one OKLCH lightness and
chroma set here. The palette and sample nodes show the range as it is set,
with how well white text reads on the hue it reads worst on. While a slider
is dragged only this dialog follows it; the editor is redrawn once it is let
go, or after a typed value or a step of the arrow keys. Cancel puts back the range there
was; Reset to Default goes back to what nxt ships with. See color_range.
"""
# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt_editor import color_range, colors, theme

# How long a slider rests before the whole editor is redrawn in the range.
APPLY_DELAY_MS = 150
READABLE = 4.5
WEAK = 3.0
SAMPLE_HUES = (('Red', 27.0), ('Yellow', 100.0), ('Blue', 262.0))
STATUS_COLORS = {'Readable': '#49cc54', 'Weak': '#e3a52d',
                 'Hard to read': '#e0564c'}


def status(ratio):
    if ratio >= READABLE:
        return 'Readable'
    if ratio >= WEAK:
        return 'Weak'
    return 'Hard to read'


# Bright colors as a layer might be given, to show what each view does
# with them: the palette's hues at their liveliest, and a grey.
EXAMPLE_LIGHTNESS = 0.74
EXAMPLE_CHROMA = 0.17


def example_color(hue, chroma=EXAMPLE_CHROMA):
    return theme.from_oklch(EXAMPLE_LIGHTNESS, chroma, hue)


def examples():
    hues = [theme.to_oklch(c)[2] for c in colors.LAYER_COLORS[:-1]]
    return [example_color(h) for h in hues] + [example_color(0.0, 0.0)]


def in_view(color, mode, lightness, chroma):
    """color as a view shows it."""
    if mode == color_range.EVEN:
        return color_range.even_color(color, lightness, chroma)
    if mode == color_range.SAFE:
        return theme.white_text_safe(color)
    return QtGui.QColor(color)


class LightnessSlider(QtWidgets.QSlider):
    """A lightness slider with a tick where white text stops reading at
    4.5:1 on every hue, and the track past it hatched."""

    def __init__(self, parent=None):
        super(LightnessSlider, self).__init__(QtCore.Qt.Horizontal, parent)
        self.limit = None

    def set_limit(self, value):
        self.limit = value
        self.update()

    def paintEvent(self, event):
        super(LightnessSlider, self).paintEvent(event)
        if self.limit is None or not self.isEnabled():
            return
        option = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QtWidgets.QStyle.CC_Slider, option,
            QtWidgets.QStyle.SC_SliderGroove, self)
        span = self.maximum() - self.minimum()
        fraction = (self.limit - self.minimum()) / float(span or 1)
        fraction = min(max(fraction, 0.0), 1.0)
        x = groove.left() + fraction * groove.width()
        painter = QtGui.QPainter(self)
        hatch = QtGui.QColor(STATUS_COLORS['Weak'])
        hatch.setAlpha(110)
        painter.fillRect(QtCore.QRectF(x, groove.center().y() - 4,
                                       groove.right() - x, 8),
                         QtGui.QBrush(hatch, QtCore.Qt.BDiagPattern))
        painter.setPen(QtGui.QPen(QtGui.QColor(STATUS_COLORS['Weak']), 2))
        painter.drawLine(QtCore.QPointF(x, groove.top() - 3),
                         QtCore.QPointF(x, groove.bottom() + 3))
        painter.end()


class PaletteStrip(QtWidgets.QWidget):
    """The layer palette in the range, white text on each."""

    def __init__(self, parent=None):
        super(PaletteStrip, self).__init__(parent)
        self.setMinimumHeight(34)
        self.colors = []

    def set_colors(self, colors_):
        self.colors = list(colors_)
        tips = ['{}  chroma {:.3f}'.format(c.name(), theme.to_oklch(c)[1])
                for c in self.colors]
        self.setToolTip('\n'.join(tips))
        self.update()

    def paintEvent(self, event):
        if not self.colors:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        width = self.width() / float(len(self.colors))
        painter.setFont(theme.font(theme.TEXT_PX, QtGui.QFont.DemiBold))
        for i, color in enumerate(self.colors):
            rect = QtCore.QRectF(i * width, 0, width, self.height())
            painter.fillRect(rect, color)
            painter.setPen(theme.color(theme.NODE_TEXT))
            painter.drawText(rect, QtCore.Qt.AlignCenter, 'Ab')


class SampleNode(QtWidgets.QWidget):
    """A node in a layer color: its title bar, white name, an attribute."""

    def __init__(self, name, parent=None):
        super(SampleNode, self).__init__(parent)
        self.name = name
        self.color = QtGui.QColor('#808080')
        self.setMinimumSize(120, 56)

    def set_color(self, color):
        self.color = QtGui.QColor(color)
        self.setToolTip('{}  white text {:.1f}:1'.format(
            self.color.name(), theme.contrast(self.color, theme.NODE_TEXT)))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        card = QtGui.QPainterPath()
        card.addRoundedRect(rect, theme.NODE_RADIUS, theme.NODE_RADIUS)
        painter.fillPath(card, theme.color(theme.NODE_BODY))
        painter.save()
        painter.setClipPath(card)
        title = QtCore.QRectF(rect.left(), rect.top(), rect.width(), 28)
        painter.fillRect(title, self.color)
        painter.restore()
        painter.setPen(theme.color(theme.NODE_TEXT))
        painter.setFont(theme.font(theme.NODE_TITLE_PX - 2,
                                   QtGui.QFont.DemiBold))
        painter.drawText(title.adjusted(10, 0, 0, 0), QtCore.Qt.AlignVCenter,
                         self.name)
        painter.setPen(theme.color(theme.TEXT_DIM))
        painter.setFont(theme.font(theme.SMALL_PX))
        painter.drawText(QtCore.QRectF(rect.left() + 10, title.bottom(),
                                       rect.width() - 20,
                                       rect.bottom() - title.bottom()),
                         QtCore.Qt.AlignVCenter, 'attr  1.0')


class ColorRangeDialog(QtWidgets.QDialog):
    """Set the range layer colors are shown in."""

    def __init__(self, parent=None, apply=None):
        """
        :param apply: called, with no arguments, to redraw the editor in
            the range as it is set
        """
        super(ColorRangeDialog, self).__init__(parent)
        self.setWindowTitle('Layer Color View')
        self.apply_editor = apply
        self.original = color_range.settings()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QtWidgets.QLabel(
            'How layer colors are shown to you. This is your view only: it '
            'does not change the color of any layer. Use Change Color on a '
            'layer for that.')
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        layout.addWidget(intro)
        # Mode.
        self.raw_radio = QtWidgets.QRadioButton('Raw (default)')
        self.raw_radio.setToolTip('Every color exactly as it is.')
        self.safe_radio = QtWidgets.QRadioButton('White-text safe')
        self.safe_radio.setToolTip('A color too light for white text is '
                                   'shown darker, just enough for it to stay '
                                   'readable (4.5:1).')
        self.even_radio = QtWidgets.QRadioButton('Even (OKLCH)')
        self.even_radio.setToolTip('Every hue at the same lightness and '
                                   'colorfulness. Looks even, and white text '
                                   'may be weaker.')
        modes = QtWidgets.QHBoxLayout()
        modes.addWidget(self.raw_radio)
        modes.addWidget(self.safe_radio)
        modes.addWidget(self.even_radio)
        modes.addStretch()
        layout.addLayout(modes)
        # Lightness and chroma.
        grid = QtWidgets.QGridLayout()
        self.lightness_slider = LightnessSlider(self)
        low, high = color_range.LIGHTNESS_RANGE
        self.lightness_slider.setRange(int(round(low * 100)),
                                       int(round(high * 100)))
        self.lightness_box = QtWidgets.QDoubleSpinBox()
        self.lightness_box.setRange(low, high)
        self.lightness_box.setSingleStep(0.01)
        self.lightness_box.setDecimals(2)
        tip = ('How light every layer color is. Higher is brighter, but '
               'white text gets harder to read.')
        for widget in (self.lightness_slider, self.lightness_box):
            widget.setToolTip(tip)
        grid.addWidget(QtWidgets.QLabel('Lightness'), 0, 0)
        grid.addWidget(self.lightness_slider, 0, 1)
        grid.addWidget(self.lightness_box, 0, 2)
        self.chroma_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        low, high = color_range.CHROMA_RANGE
        self.chroma_slider.setRange(int(round(low * 200)),
                                    int(round(high * 200)))
        self.chroma_box = QtWidgets.QDoubleSpinBox()
        self.chroma_box.setRange(low, high)
        self.chroma_box.setSingleStep(0.005)
        self.chroma_box.setDecimals(3)
        tip = 'How colorful. 0 is grey. Some hues top out early.'
        for widget in (self.chroma_slider, self.chroma_box):
            widget.setToolTip(tip)
        grid.addWidget(QtWidgets.QLabel('Chroma'), 1, 0)
        grid.addWidget(self.chroma_slider, 1, 1)
        grid.addWidget(self.chroma_box, 1, 2)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        # What it looks like.
        self.palette_strip = PaletteStrip(self)
        layout.addWidget(self.palette_strip)
        samples = QtWidgets.QHBoxLayout()
        self.samples = []
        for name, hue in SAMPLE_HUES:
            node = SampleNode(name.lower() + '_ctrl', self)
            node.hue = hue
            samples.addWidget(node)
            self.samples.append(node)
        layout.addLayout(samples)
        self.readout = QtWidgets.QLabel()
        layout.addWidget(self.readout)
        # Buttons.
        buttons = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton('Reset to Default')
        self.reset_button.setToolTip('Go back to the range nxt ships with.')
        self.reset_button.clicked.connect(self.reset)
        buttons.addWidget(self.reset_button)
        buttons.addStretch()
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)
        # The editor is redrawn once a slider is let go, or shortly after a
        # value is typed or stepped, not on every step of a drag.
        self.apply_timer = QtCore.QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(APPLY_DELAY_MS)
        self.apply_timer.timeout.connect(self.apply)
        self._setting = False
        self.set_values(*self.original)
        for radio in (self.raw_radio, self.safe_radio, self.even_radio):
            radio.toggled.connect(self.on_changed)
        self.lightness_slider.valueChanged.connect(self.on_lightness_slider)
        self.lightness_box.valueChanged.connect(self.on_lightness_box)
        self.chroma_slider.valueChanged.connect(self.on_chroma_slider)
        self.chroma_box.valueChanged.connect(self.on_chroma_box)
        for slider in (self.lightness_slider, self.chroma_slider):
            slider.sliderReleased.connect(self.apply)
        self.resize(560, 330)

    # Values ------------------------------------------------------------

    def values(self):
        """(mode, lightness, chroma) as set here."""
        if self.even_radio.isChecked():
            mode = color_range.EVEN
        elif self.safe_radio.isChecked():
            mode = color_range.SAFE
        else:
            mode = color_range.RAW
        return mode, self.lightness_box.value(), self.chroma_box.value()

    def set_values(self, mode, lightness, chroma):
        self._setting = True
        try:
            self.even_radio.setChecked(mode == color_range.EVEN)
            self.safe_radio.setChecked(mode == color_range.SAFE)
            self.raw_radio.setChecked(mode not in (color_range.EVEN,
                                                   color_range.SAFE))
            self.lightness_box.setValue(lightness)
            self.lightness_slider.setValue(int(round(lightness * 100)))
            self.chroma_box.setValue(chroma)
            self.chroma_slider.setValue(int(round(chroma * 200)))
        finally:
            self._setting = False
        self.update_preview()

    def on_lightness_slider(self, value):
        if not self._setting:
            self._setting = True
            self.lightness_box.setValue(value / 100.0)
            self._setting = False
            self.on_changed()

    def on_lightness_box(self, value):
        if not self._setting:
            self._setting = True
            self.lightness_slider.setValue(int(round(value * 100)))
            self._setting = False
            self.on_changed()

    def on_chroma_slider(self, value):
        if not self._setting:
            self._setting = True
            self.chroma_box.setValue(value / 200.0)
            self._setting = False
            self.on_changed()

    def on_chroma_box(self, value):
        if not self._setting:
            self._setting = True
            self.chroma_slider.setValue(int(round(value * 200)))
            self._setting = False
            self.on_changed()

    def on_changed(self, *args):
        if self._setting:
            return
        self.update_preview()
        # While a slider is dragged only this dialog follows it. The
        # editor is redrawn once it is let go, see apply.
        if (self.lightness_slider.isSliderDown() or
                self.chroma_slider.isSliderDown()):
            self.apply_timer.stop()
            return
        self.apply_timer.start()

    # Preview -----------------------------------------------------------

    def update_preview(self):
        mode, lightness, chroma = self.values()
        even = mode == color_range.EVEN
        for widget in (self.lightness_slider, self.lightness_box,
                       self.chroma_slider, self.chroma_box):
            widget.setEnabled(even)
        palette = [in_view(c, mode, lightness, chroma) for c in examples()]
        self.palette_strip.set_colors(palette)
        for node in self.samples:
            node.set_color(in_view(example_color(node.hue), mode, lightness,
                                   chroma))
        self.lightness_slider.set_limit(
            color_range.readable_limit(chroma) * 100 if even else None)
        if even:
            ratio, hue = color_range.worst_contrast(lightness, chroma)
            text = 'White text: {:.1f}:1 (lowest, {})'.format(
                ratio, color_range.hue_name(hue))
        else:
            ratios = [(theme.contrast(c, theme.NODE_TEXT), c)
                      for c in palette]
            ratio, worst = min(ratios, key=lambda pair: pair[0])
            if mode == color_range.SAFE:
                text = ('White text: {:.1f}:1 or better on every '
                        'color'.format(ratio))
            else:
                text = ('White text: as low as {:.1f}:1 on light colors '
                        '(lowest, {})'.format(ratio, color_range.hue_name(
                            theme.to_oklch(worst)[2])))
        state = status(ratio)
        self.readout.setText(
            '{}  <span style="color:{}; font-weight:600">{}</span>'.format(
                text, STATUS_COLORS[state], state))

    # Applying ----------------------------------------------------------

    def apply(self, save=False):
        """Show the editor in the range as set here."""
        self.apply_timer.stop()
        color_range.set_settings(*self.values(), save=save)
        if self.apply_editor:
            self.apply_editor()

    def reset(self):
        """Back to the view nxt ships with, raw, applied on OK."""
        self.set_values(color_range.DEFAULT, color_range.DEFAULT_LIGHTNESS,
                        color_range.DEFAULT_CHROMA)
        self.apply_timer.start()

    def accept(self):
        self.apply(save=True)
        super(ColorRangeDialog, self).accept()

    def reject(self):
        self.apply_timer.stop()
        color_range.set_settings(*self.original, save=False)
        if self.apply_editor:
            self.apply_editor()
        super(ColorRangeDialog, self).reject()
