"""The Layer Manager's toggle columns are drawn icons, not letters.

Display, mute, solo, lock and the eye each paint a small icon, on a chip
of the layer's color when the toggle is on and as a dim outline when it is
off. Each cell has a tooltip that says what a click does and what the
toggle means, and changes with the state. Clicking still toggles exactly
as the letters did.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtCore, QtGui, QtTest, QtWidgets

# Internal
from nxt_editor.dockwidgets.layer_manager import (DisplayIconDelegate,
                                                   EyeCheckboxDelegate,
                                                   LayerModel,
                                                   LockIconDelegate,
                                                   MuteIconDelegate,
                                                   SoloIconDelegate)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

ICON_COLUMNS = (LayerModel.DISPLAY_COLUMN, LayerModel.MUTE_COLUMN,
                LayerModel.SOLO_COLUMN, LayerModel.LOCK_COLUMN,
                LayerModel.VISIBLE_COLUMN)
DELEGATES = (DisplayIconDelegate, MuteIconDelegate, SoloIconDelegate,
             LockIconDelegate, EyeCheckboxDelegate)


def write(path, data):
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


class LayerIcons(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_layer_icon_'))
        write(os.path.join(cls.tmp, 'library.nxt'), {
            'version': '1.17', 'alias': 'library', 'references': [],
            'nodes': {'/template': {}}})
        cls.top = write(os.path.join(cls.tmp, 'top.nxt'), {
            'version': '1.17', 'alias': 'top', 'references': ['library.nxt'],
            'nodes': {'/made': {}}})
        cls.win = MainWindow(filepath=cls.top)
        cls.win.show()
        app.processEvents()
        cls.model = cls.win.model
        cls.tree = cls.win.layer_manager.layer_tree
        cls.library = cls.model.stage._sub_layers[1]

    @classmethod
    def tearDownClass(cls):
        # Muting and locking leave layers unsaved, and closing would ask.
        cls.model.effected_layers.clear()
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.reset()
        self.addCleanup(self.reset)

    def reset(self):
        model = self.model
        if self.library.get_muted():
            model.mute_toggle_layer(self.library)
        if self.library.get_soloed():
            model.solo_toggle_layer(self.library)
        path = model.get_layer_path(self.library)
        if self.library.get_locked():
            model.set_layer_locked(path, lock=False)
        model.set_layer_hidden(self.library.real_path, False)
        if model.display_layer is not model.top_layer:
            model.set_display_layer(model.top_layer)
        app.processEvents()

    def cell(self, column, layer=None):
        layer_model = self.tree.model()
        index = layer_model.get_index_of_layer(layer or self.library)
        return layer_model.index(index.row(), column, index.parent())

    def tip(self, column, layer=None):
        return self.cell(column, layer).data(QtCore.Qt.ToolTipRole)

    def click(self, column, layer=None):
        spot = self.tree.visualRect(self.cell(column, layer)).center()
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton,
                                pos=spot)
        app.processEvents()

    # -- no letters --------------------------------------------------------

    def test_no_letters_are_shown(self):
        for column in ICON_COLUMNS:
            text = self.cell(column).data(QtCore.Qt.DisplayRole)
            self.assertFalse(text, column)

    def test_each_column_has_its_icon(self):
        for column, delegate in zip(ICON_COLUMNS, DELEGATES):
            self.assertIsInstance(self.tree.itemDelegateForColumn(column),
                                  delegate)

    # -- tooltips ----------------------------------------------------------

    def test_every_icon_has_a_tooltip(self):
        for column in ICON_COLUMNS:
            self.assertTrue(self.tip(column), column)
            self.assertTrue(self.cell(column).data(
                QtCore.Qt.AccessibleTextRole), column)
            self.assertTrue(self.cell(column).data(
                QtCore.Qt.AccessibleDescriptionRole), column)

    def test_the_mute_tooltip_follows_the_state(self):
        self.assertTrue(self.tip(LayerModel.MUTE_COLUMN).startswith(
            'Mute layer'))
        self.model.mute_toggle_layer(self.library)
        self.assertTrue(self.tip(LayerModel.MUTE_COLUMN).startswith(
            'Unmute layer'))

    def test_the_solo_tooltip_follows_the_state(self):
        self.assertTrue(self.tip(LayerModel.SOLO_COLUMN).startswith(
            'Solo layer'))
        self.model.solo_toggle_layer(self.library)
        self.assertTrue(self.tip(LayerModel.SOLO_COLUMN).startswith(
            'Unsolo layer'))

    def test_the_lock_tooltip_follows_the_state(self):
        self.assertTrue(self.tip(LayerModel.LOCK_COLUMN).startswith(
            'Lock layer'))
        self.model.set_layer_locked(self.model.get_layer_path(self.library),
                                    lock=True)
        self.assertTrue(self.tip(LayerModel.LOCK_COLUMN).startswith(
            'Unlock layer'))

    def test_the_eye_tooltip_follows_the_state(self):
        self.assertTrue(self.tip(LayerModel.VISIBLE_COLUMN).startswith(
            "Hide layer's nodes"))
        self.model.set_layer_hidden(self.library.real_path, True)
        self.assertTrue(self.tip(LayerModel.VISIBLE_COLUMN).startswith(
            "Show layer's nodes"))

    def test_the_display_tooltip_follows_the_state(self):
        column = LayerModel.DISPLAY_COLUMN
        top = self.model.top_layer
        self.assertTrue(self.tip(column, top).startswith(
            'This is the display layer'))
        self.assertTrue(self.tip(column).startswith(
            'Display from this layer'))

    # -- clicking ----------------------------------------------------------

    def test_clicking_mute_toggles_and_undoes(self):
        self.click(LayerModel.MUTE_COLUMN)
        self.assertTrue(self.library.get_muted())
        self.model.undo_stack.undo()
        self.assertFalse(self.library.get_muted())
        self.click(LayerModel.MUTE_COLUMN)
        self.click(LayerModel.MUTE_COLUMN)
        self.assertFalse(self.library.get_muted())

    def test_clicking_solo_toggles(self):
        self.click(LayerModel.SOLO_COLUMN)
        self.assertTrue(self.library.get_soloed())
        self.click(LayerModel.SOLO_COLUMN)
        self.assertFalse(self.library.get_soloed())

    def test_clicking_lock_toggles(self):
        self.click(LayerModel.LOCK_COLUMN)
        self.assertTrue(self.library.get_locked())
        self.click(LayerModel.LOCK_COLUMN)
        self.assertFalse(self.library.get_locked())

    def test_clicking_the_eye_toggles(self):
        path = self.library.real_path
        self.click(LayerModel.VISIBLE_COLUMN)
        self.assertTrue(self.model.get_layer_hidden(path))
        self.click(LayerModel.VISIBLE_COLUMN)
        self.assertFalse(self.model.get_layer_hidden(path))

    def test_clicking_display_picks_the_display_layer(self):
        self.click(LayerModel.DISPLAY_COLUMN)
        self.assertIs(self.library, self.model.display_layer)
        # Clicking the display layer again leaves it as it is.
        self.click(LayerModel.DISPLAY_COLUMN)
        self.assertIs(self.library, self.model.display_layer)

    def test_a_right_click_toggles_nothing(self):
        spot = self.tree.visualRect(self.cell(LayerModel.MUTE_COLUMN))
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.RightButton,
                                pos=spot.center())
        app.processEvents()
        for widget in app.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMenu):
                widget.close()
        self.assertFalse(self.library.get_muted())

    # -- hover -------------------------------------------------------------

    def test_the_cell_under_the_mouse_is_tracked(self):
        cell = self.cell(LayerModel.LOCK_COLUMN)
        self.tree.set_hover_index(cell)
        self.assertEqual(cell, QtCore.QModelIndex(self.tree.hover_index))
        self.tree.set_hover_index(QtCore.QModelIndex())
        self.assertFalse(self.tree.hover_index.isValid())


class Painting(unittest.TestCase):
    """Every icon paints, on and off, without the editor around it."""

    def paint(self, delegate, checked, hovered=False):
        model = QtGui.QStandardItemModel(1, 1)
        item = QtGui.QStandardItem()
        item.setCheckable(True)
        item.setCheckState(QtCore.Qt.Checked if checked
                           else QtCore.Qt.Unchecked)
        item.setBackground(QtGui.QBrush(QtGui.QColor('#6b9ac2')))
        model.setItem(0, 0, item)
        index = model.index(0, 0)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 25, 25)
        if hovered:
            view = QtWidgets.QWidget()
            view.hover_index = QtCore.QPersistentModelIndex(index)
            option.widget = view
        image = QtGui.QImage(25, 25, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        try:
            delegate().paint(painter, option, index)
        finally:
            painter.end()
        return image

    def test_every_icon_paints_on_and_off(self):
        blank = QtGui.QImage(25, 25, QtGui.QImage.Format_ARGB32)
        blank.fill(QtCore.Qt.transparent)
        for delegate in DELEGATES:
            on = self.paint(delegate, True)
            off = self.paint(delegate, False)
            self.assertNotEqual(blank, on, delegate.__name__)
            self.assertNotEqual(blank, off, delegate.__name__)
            self.assertNotEqual(on, off, delegate.__name__)

    def test_hover_changes_the_cell(self):
        for delegate in DELEGATES:
            self.assertNotEqual(self.paint(delegate, False),
                                self.paint(delegate, False, hovered=True),
                                delegate.__name__)

    def test_on_is_a_chip_of_the_layer_color(self):
        # The corner of the chip, clear of the glyph. Which state is "on"
        # differs for the eye: it lights up when the layer is hidden.
        for delegate in DELEGATES:
            checked = delegate is not EyeCheckboxDelegate
            corner = self.paint(delegate, checked).pixelColor(3, 3)
            self.assertEqual(QtGui.QColor('#6b9ac2').rgb(), corner.rgb(),
                             delegate.__name__)
            corner = self.paint(delegate, not checked).pixelColor(3, 3)
            self.assertEqual(0, corner.alpha(), delegate.__name__)


if __name__ == '__main__':
    unittest.main()
