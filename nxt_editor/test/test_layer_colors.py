"""Layer colors are ones white text reads on.

Nodes, Outliner rows and the layer list show names in white on their
layer's color. The palette, a color saved before this or set from a
script, and anything picked in the color picker are all kept dark enough
for it to read.
"""
# Builtin
import random
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import colors, theme
from nxt_editor.layer_color_dialog import LayerColorDialog
from nxt_editor.stage_model import StageModel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def reads(color):
    return theme.contrast(color, theme.NODE_TEXT) >= \
        theme.WHITE_TEXT_CONTRAST


class WhiteTextSafe(unittest.TestCase):

    def test_the_palette_is_safe(self):
        for color in colors.LAYER_COLORS:
            self.assertTrue(reads(color), color.name())

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


class TheModel(unittest.TestCase):

    def setUp(self):
        self.model = StageModel(Session().new_file())

    def test_a_bright_saved_color_is_shown_safe(self):
        layer = self.model.top_layer
        layer.color = '#ffee00'
        shown = self.model.get_layer_color(layer)
        self.assertTrue(reads(shown), shown)

    def test_a_bright_color_set_is_stored_safe(self):
        layer = self.model.top_layer
        self.model.set_layer_color(LayerTop(self.model), '#99cc33')
        stored = layer.get_color(local=True)
        self.assertTrue(reads(stored), stored)


def LayerTop(model):
    from nxt.nxt_layer import LAYERS
    return LAYERS.TOP


class Backdrops(unittest.TestCase):
    """Backdrops take the same colors as layers: their titles are white
    on them too."""

    def setUp(self):
        self.model = StageModel(Session().new_file())

    def test_a_bright_color_is_stored_safe(self):
        from nxt_editor import backdrops
        backdrop_id = self.model.add_backdrop({backdrops.COLOR: '#ffee00'})
        color = self.model.get_backdrop(backdrop_id)[backdrops.COLOR]
        self.assertTrue(reads(color), color)
        self.model.edit_backdrop(backdrop_id, color='#ffffff')
        color = self.model.get_backdrop(backdrop_id)[backdrops.COLOR]
        self.assertTrue(reads(color), color)

    def test_a_bright_saved_color_is_drawn_safe(self):
        from nxt_editor import backdrops
        from nxt_editor.backdrop_graphics_item import BackdropGraphicsItem
        record = backdrops.clean({backdrops.COLOR: '#99cc33'})
        graphic = BackdropGraphicsItem('id', record)
        self.assertTrue(reads(graphic.color()))

    def test_the_presets_are_safe(self):
        from nxt_editor import backdrops
        for name, color in backdrops.PRESET_COLORS:
            self.assertTrue(reads(color), name)


class ThePicker(unittest.TestCase):

    def setUp(self):
        self.dialog = LayerColorDialog('#ffee00')
        self.dialog.resize(420, 330)
        self.dialog.show()
        app.processEvents()

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        app.processEvents()

    def test_a_bright_starting_color_is_offered_safe(self):
        self.assertTrue(reads(self.dialog.color))

    def test_anywhere_picked_is_safe(self):
        rng = random.Random(7)
        field, bar = self.dialog.field, self.dialog.shade_bar
        for _ in range(40):
            point = QtCore.QPoint(rng.randrange(field.width()),
                                  rng.randrange(field.height()))
            field.pick(point)
            bar.pick(QtCore.QPoint(5, rng.randrange(bar.height())))
            self.assertTrue(reads(self.dialog.color),
                            self.dialog.color.name())
        # The top of the shade bar is the lightest that still reads.
        bar.pick(QtCore.QPoint(5, 0))
        self.assertTrue(reads(self.dialog.color))

    def test_a_typed_bright_hex_is_taken_safe(self):
        self.dialog.hex_edit.setText('#ffffff')
        self.dialog.on_hex_edited()
        self.assertTrue(reads(self.dialog.color))
        self.assertEqual(self.dialog.color.name(),
                         self.dialog.hex_edit.text())

    def test_the_palette_is_offered(self):
        self.assertEqual(len(colors.LAYER_COLORS), len(self.dialog.swatches))
        self.dialog.swatches[2].click()
        self.assertEqual(colors.LAYER_COLORS[2].name(),
                         self.dialog.color.name())


if __name__ == '__main__':
    unittest.main()
