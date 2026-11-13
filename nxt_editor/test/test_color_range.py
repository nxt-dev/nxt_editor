"""How layer colors are shown to a user, a view preference.

Raw, the default, shows every color as it is. White-text safe shows a color
too light for white text darker. Even shows every color at one OKLCH
lightness and chroma, keeping its hue. Stored colors are never rewritten
for it, so changing the range loses nothing, and choosing a layer's color
in Change Color is the same whatever the view. View > Options > Layer Color
View sets it, with a live preview, and remembers it on OK; Cancel puts the
range back and Reset to Default goes back to what nxt ships with.
"""
# Builtin
import random
import sys
import unittest
from unittest import mock

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt.nxt_layer import LAYERS
from nxt.session import Session
from nxt_editor import color_range, colors, theme, user_dir
from nxt_editor.color_range_dialog import ColorRangeDialog
from nxt_editor.dockwidgets.outliner import LAYERS_ROLE
from nxt_editor.layer_color_dialog import LayerColorDialog
from nxt_editor.stage_model import StageModel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

KEYS = (user_dir.USER_PREF.COLOR_RANGE_MODE,
        user_dir.USER_PREF.COLOR_RANGE_LIGHTNESS,
        user_dir.USER_PREF.COLOR_RANGE_CHROMA)


class RangeCase(unittest.TestCase):

    def setUp(self):
        saved = {key: (key in user_dir.user_prefs,
                       user_dir.user_prefs.get(key)) for key in KEYS}

        def restore():
            for key, (had, value) in saved.items():
                if had:
                    user_dir.user_prefs[key] = value
                elif key in user_dir.user_prefs:
                    user_dir.user_prefs.pop(key)
            color_range.forget()
        self.addCleanup(restore)
        for key in KEYS:
            if key in user_dir.user_prefs:
                user_dir.user_prefs.pop(key)
        color_range.forget()

    def even(self, lightness=0.65, chroma=0.15):
        color_range.set_settings(color_range.EVEN, lightness, chroma,
                                 save=False)


def near(a, b, tolerance=0.01):
    return abs(a - b) <= tolerance


class Shown(RangeCase):

    def test_the_default_is_raw(self):
        self.assertEqual(color_range.RAW, color_range.mode())
        for name in ('#ffee00', '#991c24', '#ffffff'):
            self.assertEqual(name, color_range.shown(name).name())

    def test_white_text_safe_darkens_only_what_is_too_light(self):
        color_range.set_settings(color_range.SAFE, 0.65, 0.15, save=False)
        for name in ('#ffee00', '#991c24'):
            self.assertEqual(theme.white_text_safe(name).name(),
                             color_range.shown(name).name())
        self.assertEqual('#991c24', color_range.shown('#991c24').name())

    def test_even_keeps_the_hue_at_the_lightness_and_chroma(self):
        self.even(0.6, 0.12)
        for name in ('#ffee00', '#991c24', '#0052aa', '#00a5e6'):
            lightness, chroma, hue = theme.to_oklch(color_range.shown(name))
            self.assertTrue(near(0.6, lightness), name)
            self.assertTrue(chroma <= 0.125, name)
            self.assertLess(abs((hue - theme.to_oklch(name)[2] + 180) % 360
                                - 180), 3, name)

    def test_even_keeps_a_grey_grey(self):
        self.even(0.7, 0.15)
        lightness, chroma, _ = theme.to_oklch(color_range.shown('#787878'))
        self.assertTrue(near(0.7, lightness))
        self.assertLess(chroma, 0.01)

    def test_the_palette_is_shown_in_the_range(self):
        self.even(0.7, 0.1)
        for color in colors.LAYER_COLORS:
            shown = color_range.shown(color)
            self.assertTrue(near(0.7, theme.to_oklch(shown)[0]))


class Stored(RangeCase):

    def setUp(self):
        super(Stored, self).setUp()
        self.model = StageModel(Session().new_file())

    def test_changing_the_range_rewrites_nothing(self):
        layer = self.model.top_layer
        layer.color = '#c91781'
        default = self.model.get_layer_color(layer)
        self.even(0.75, 0.1)
        self.assertNotEqual(default, self.model.get_layer_color(layer))
        self.assertEqual('#c91781', layer.color)
        color_range.set_settings(color_range.DEFAULT, 0.65, 0.15, save=False)
        self.assertEqual(default, self.model.get_layer_color(layer))

    def test_a_color_chosen_is_stored_as_chosen_in_any_view(self):
        self.model.set_layer_color(LAYERS.TOP, '#ffee00')
        self.assertEqual('#ffee00', self.model.top_layer.get_color(local=True))
        self.model.set_layer_color(LAYERS.TOP, '#991c24')
        self.even(0.75, 0.1)
        self.model.set_layer_color(LAYERS.TOP, '#ffee00')
        self.assertEqual('#ffee00', self.model.top_layer.get_color(local=True))


class Contrast(RangeCase):

    def test_the_readable_limit_is_where_white_text_reaches_4_5(self):
        for chroma in (0.0, 0.08, 0.15):
            limit = color_range.readable_limit(chroma)
            self.assertGreaterEqual(
                color_range.worst_contrast(limit, chroma)[0], 4.5)
            self.assertLess(
                color_range.worst_contrast(limit + 0.02, chroma)[0], 4.5)

    def test_lighter_is_harder_to_read(self):
        dark = color_range.worst_contrast(0.5, 0.12)[0]
        light = color_range.worst_contrast(0.75, 0.12)[0]
        self.assertGreater(dark, light)


class TheDialog(RangeCase):

    def setUp(self):
        super(TheDialog, self).setUp()
        self.applied = []
        self.dialog = ColorRangeDialog(
            apply=lambda: self.applied.append(color_range.settings()))
        self.dialog.show()
        app.processEvents()

    def tearDown(self):
        self.dialog.deleteLater()
        app.processEvents()

    def test_it_opens_on_raw_with_the_sliders_off(self):
        self.assertTrue(self.dialog.raw_radio.isChecked())
        self.assertFalse(self.dialog.lightness_slider.isEnabled())
        self.assertIn('as low as', self.dialog.readout.text())

    def test_white_text_safe_reads(self):
        self.dialog.safe_radio.setChecked(True)
        self.assertFalse(self.dialog.lightness_slider.isEnabled())
        self.assertIn('Readable', self.dialog.readout.text())
        self.assertEqual(color_range.SAFE, self.dialog.values()[0])

    def test_the_editor_waits_for_a_dragged_slider_to_be_let_go(self):
        from Qt import QtTest
        self.dialog.even_radio.setChecked(True)
        QtTest.QTest.qWait(300)
        del self.applied[:]
        slider = self.dialog.lightness_slider
        slider.setSliderDown(True)
        for value in (70, 72, 74):
            slider.setValue(value)
            QtTest.QTest.qWait(200)
        # The dialog follows the drag, the editor does not.
        self.assertTrue(near(0.74, self.dialog.lightness_box.value()))
        self.assertEqual([], self.applied)
        # Let go, which Qt tells the slider as sliderReleased.
        slider.setSliderDown(False)
        self.assertEqual([(color_range.EVEN, 0.74, 0.15)], self.applied)
        # Tried, not remembered.
        self.assertNotIn(KEYS[0], user_dir.user_prefs)

    def test_a_typed_value_is_applied_after_a_moment(self):
        from Qt import QtTest
        self.dialog.even_radio.setChecked(True)
        self.dialog.chroma_box.setValue(0.1)
        self.assertEqual([], self.applied)
        # A moment, however long the event loop takes to get to it.
        for _ in range(60):
            QtTest.QTest.qWait(50)
            if self.applied:
                break
        self.assertEqual((color_range.EVEN, 0.65, 0.1), self.applied[-1])

    def test_ok_remembers_it(self):
        self.dialog.even_radio.setChecked(True)
        self.dialog.chroma_box.setValue(0.1)
        self.dialog.accept()
        self.assertEqual(color_range.EVEN, user_dir.user_prefs.get(KEYS[0]))
        self.assertTrue(near(0.1, user_dir.user_prefs.get(KEYS[2]), 0.001))
        color_range.forget()
        self.assertEqual(color_range.EVEN, color_range.mode())

    def test_cancel_puts_the_range_back(self):
        self.dialog.even_radio.setChecked(True)
        self.dialog.apply()
        self.assertEqual(color_range.EVEN, color_range.mode())
        self.dialog.reject()
        self.assertEqual(color_range.DEFAULT, color_range.mode())
        self.assertEqual(color_range.DEFAULT, self.applied[-1][0])

    def test_reset_goes_back_to_the_default(self):
        self.dialog.even_radio.setChecked(True)
        self.dialog.lightness_box.setValue(0.5)
        self.dialog.accept()
        dialog = ColorRangeDialog()
        dialog.reset()
        self.assertTrue(dialog.raw_radio.isChecked())
        self.assertTrue(near(color_range.DEFAULT_LIGHTNESS,
                             dialog.lightness_box.value()))
        dialog.accept()
        self.assertEqual(color_range.DEFAULT,
                         user_dir.user_prefs.get(KEYS[0]))

    def test_weak_white_text_is_called_out(self):
        self.dialog.even_radio.setChecked(True)
        self.dialog.lightness_box.setValue(0.78)
        self.assertIn('Hard to read', self.dialog.readout.text())
        self.assertIsNotNone(self.dialog.lightness_slider.limit)


class ThePicker(RangeCase):
    """Change Color chooses a layer's actual color, whatever the view."""

    def open(self, color='#ffee00'):
        dialog = LayerColorDialog(color)
        dialog.show()
        app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_it_is_the_same_in_any_view(self):
        default = self.open()
        default_color = default.color.name()
        self.even(0.75, 0.1)
        even = self.open()
        self.assertEqual(default_color, even.color.name())
        self.assertTrue(even.field.isVisible())
        for i, color in enumerate(colors.LAYER_COLORS):
            even.swatches[i].click()
            self.assertEqual(color.name(), even.color.name())

    def test_it_shows_how_the_color_will_look_in_your_view(self):
        dialog = self.open('#ffee00')
        self.assertTrue(dialog.view_preview.isVisible())
        self.assertEqual(color_range.shown(dialog.color).name(),
                         dialog.view_preview.color.name())
        self.even(0.75, 0.1)
        dialog = self.open('#991c24')
        self.assertEqual(color_range.shown(dialog.color).name(),
                         dialog.view_preview.color.name())


class TheEditor(RangeCase):

    def test_everything_is_redrawn_in_a_new_range(self):
        from nxt_editor import stage_model
        from nxt_editor.main_window import MainWindow
        win = MainWindow()
        win.show()
        win.new_tab()
        app.processEvents()
        model = win.model
        model.add_node(name='node', pos=(0, 0))
        win.outliner.show()
        win.instance_view.show()
        app.processEvents()
        before = win.view.get_node_graphic('/node').colors[-1].name()
        self.even(0.78, 0.12)
        win.refresh_layer_colors()
        app.processEvents()
        after = win.view.get_node_graphic('/node').colors[-1].name()
        self.assertNotEqual(before, after)
        self.assertTrue(near(0.78, theme.to_oklch(after)[0]))
        self.assertEqual(after,
                         win.outliner.items['/node'].data(0, LAYERS_ROLE)[0])
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            win.close()
            app.processEvents()
        win.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    unittest.main()
