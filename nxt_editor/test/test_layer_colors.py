"""Layer colors are any color, and shown so white text reads on them.

A layer or backdrop is given exactly the color picked, from the full
spectrum. How it is shown is the user's view, see color_range: raw by
default, or in the white-text safe view a color too light for the white
names on it is shown darker, keeping its hue, without being changed.
"""
# Builtin
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import color_range, colors, theme
from nxt_editor.layer_color_dialog import LayerColorDialog
from nxt_editor.stage_model import StageModel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class SafeView(unittest.TestCase):
    """In the white-text safe view."""

    def setUp(self):
        color_range.set_settings(color_range.SAFE, 0.65, 0.15, save=False)
        self.addCleanup(color_range.forget)


def reads(color):
    return theme.contrast(color, theme.NODE_TEXT) >= \
        theme.WHITE_TEXT_CONTRAST


class WhiteTextSafe(unittest.TestCase):

    def test_the_palette_is_safe(self):
        for color in colors.LAYER_COLORS:
            self.assertTrue(reads(color), color.name())

    def test_the_palette_hues_are_spread_out(self):
        def hue(color):
            return theme.to_oklch(color)[2]

        def apart(a, b):
            d = abs(a - b) % 360.0
            return min(d, 360.0 - d)
        hues = [hue(c) for c in colors.LAYER_COLORS[:-1]]
        for i, a in enumerate(hues):
            for b in hues[i + 1:]:
                self.assertGreater(apart(a, b), 12)
        # Each layer added gets a hue well away from the one before.
        for a, b in zip(hues, hues[1:]):
            self.assertGreater(apart(a, b), 60)

    def test_a_safe_color_is_kept(self):
        for name in ('#991c24', '#0052aa', '#6e33bb'):
            self.assertEqual(name, theme.white_text_safe(name).name())

    def test_a_bright_color_keeps_its_hue_and_only_darkens(self):
        for name in ('#ffee00', '#99cc33', '#00a5e6', '#ffffff', '#f38b00'):
            original = QtGui.QColor(name)
            safe = theme.white_text_safe(name)
            self.assertTrue(reads(safe), name)
            self.assertLess(safe.lightnessF(), original.lightnessF())
            if original.saturationF() > 0:
                self.assertAlmostEqual(original.hueF(), safe.hueF(),
                                       delta=0.02)
            # As light as it can be and still read: a bit lighter does not.
            lighter = QtGui.QColor.fromHslF(
                max(safe.hueF(), 0), safe.saturationF(),
                min(safe.lightnessF() + 0.02, 1.0))
            self.assertFalse(reads(lighter), name)


class TheModel(SafeView):

    def setUp(self):
        super(TheModel, self).setUp()
        self.model = StageModel(Session().new_file())

    def test_a_bright_color_is_kept_and_shown_safe(self):
        from nxt.nxt_layer import LAYERS
        self.model.set_layer_color(LAYERS.TOP, '#ffee00')
        self.assertEqual('#ffee00',
                         self.model.top_layer.get_color(local=True))
        shown = self.model.get_layer_color(self.model.top_layer)
        self.assertTrue(reads(shown), shown)


class Backdrops(SafeView):
    """Backdrops are the same: any color, shown so white text reads."""

    def setUp(self):
        super(Backdrops, self).setUp()
        self.model = StageModel(Session().new_file())

    def test_a_bright_color_is_kept(self):
        from nxt_editor import backdrops
        backdrop_id = self.model.add_backdrop({backdrops.COLOR: '#ffee00'})
        self.assertEqual('#ffee00',
                         self.model.get_backdrop(backdrop_id)[backdrops.COLOR])

    def test_a_bright_color_is_drawn_safe(self):
        from nxt_editor import backdrops
        from nxt_editor.backdrop_graphics_item import BackdropGraphicsItem
        record = backdrops.clean({backdrops.COLOR: '#99cc33'})
        graphic = BackdropGraphicsItem('id', record)
        self.assertTrue(reads(graphic.color()))


class ThePicker(SafeView):
    """Change Color picks from the full spectrum."""

    def setUp(self):
        super(ThePicker, self).setUp()
        self.dialog = LayerColorDialog('#ffee00')
        self.dialog.resize(420, 330)
        self.dialog.show()
        app.processEvents()

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        app.processEvents()

    def test_a_bright_starting_color_is_kept(self):
        self.assertEqual('#ffee00', self.dialog.color.name())

    def test_the_brightest_and_darkest_can_be_picked(self):
        field, bar = self.dialog.field, self.dialog.shade_bar
        field.pick(QtCore.QPoint(field.width() // 6, 0))
        bar.pick(QtCore.QPoint(5, 0))
        brightest = self.dialog.color
        self.assertGreater(brightest.valueF(), 0.99)
        self.assertGreater(brightest.saturationF(), 0.95)
        bar.pick(QtCore.QPoint(5, bar.height() - 1))
        self.assertLess(self.dialog.color.valueF(), 0.01)

    def test_a_typed_hex_is_taken_as_it_is(self):
        for name in ('#ffffff', '#00ff7f', '#123456'):
            self.dialog.hex_edit.setText(name)
            self.dialog.on_hex_edited()
            self.assertEqual(name, self.dialog.color.name())

    def test_it_shows_how_the_color_will_look_in_your_view(self):
        self.assertTrue(self.dialog.view_preview.isVisible())
        self.assertEqual(theme.white_text_safe('#ffee00').name(),
                         self.dialog.view_preview.color.name())

    def test_the_palette_is_offered(self):
        self.assertEqual(len(colors.LAYER_COLORS), len(self.dialog.swatches))
        for i, color in enumerate(colors.LAYER_COLORS):
            self.dialog.swatches[i].click()
            self.assertEqual(color.name(), self.dialog.color.name())


if __name__ == '__main__':
    unittest.main()
