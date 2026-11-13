"""Attribute rows can read on the dark panel whatever their layer's color.

Rows used to be colored by their layer, lighter where the node sets the
value and darker where it inherits it. Layer colors are dark enough to
carry white text, so inherited rows all but disappeared. Now the text is
neutral, bright for a value set here and softer for one from elsewhere,
and the layer shows as the color of the row's header, which stays in view
however far the table is scrolled.

It is an option, View > Options > Neutral Property Text, off by default
and remembered with the user's preferences.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt_editor import stage_model, theme, user_dir
from nxt_editor.dockwidgets import property_editor
from nxt_editor.dockwidgets.property_editor import (COLUMNS, LAYER_COLOR_ROLE,
                                                    PropertyEditor)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'props', 'color': '#0052aa', 'nodes': {
    '/rig': {'attrs': {'side': {'type': 'raw', 'value': 'L'}}},
    '/rig/arm': {'attrs': {'name': {'type': 'raw', 'value': 'arm'}}}}}


class Rows(unittest.TestCase):

    def setUp(self):
        key = user_dir.USER_PREF.NEUTRAL_PROPERTY_TEXT
        had = key in user_dir.user_prefs
        saved = user_dir.user_prefs.get(key)

        def restore():
            if had:
                user_dir.user_prefs[key] = saved
            elif key in user_dir.user_prefs:
                user_dir.user_prefs.pop(key)
            del property_editor._neutral_text[:]
        self.addCleanup(restore)
        property_editor.set_neutral_text(True)
        self.tmp = tempfile.mkdtemp(prefix='nxt_props_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'props.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.win.model.set_selection(['/rig/arm'])
        app.processEvents()
        self.editor = self.win.findChild(PropertyEditor)
        self.model = self.editor.model

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def row(self, attr_name):
        for row in range(self.model.rowCount(None)):
            index = self.model.index(row, COLUMNS.name)
            if self.model.data(index) == attr_name:
                return row
        self.fail('no row for ' + attr_name)

    def data(self, attr_name, column, role):
        return self.model.data(self.model.index(self.row(attr_name), column),
                               role)

    def test_local_and_inherited_text_both_read(self):
        from Qt import QtCore
        local = self.data('name', COLUMNS.value, QtCore.Qt.ForegroundRole)
        inherited = self.data('side', COLUMNS.value, QtCore.Qt.ForegroundRole)
        self.assertNotEqual(local.name(), inherited.name())
        for color in (local, inherited):
            self.assertGreaterEqual(theme.contrast(color, theme.BASE), 4.5,
                                    color.name())

    def test_a_value_set_here_is_bold_across_its_row(self):
        from Qt import QtCore
        for column in (COLUMNS.name, COLUMNS.value, COLUMNS.nxt_type,
                       COLUMNS.source):
            font = self.data('name', column, QtCore.Qt.FontRole)
            self.assertGreater(font.weight(), QtGui.QFont.Normal, column)
            self.assertIsNone(self.data('side', column, QtCore.Qt.FontRole))

    def test_the_layer_is_shown_by_its_color(self):
        layer_color = self.win.model.get_layer_color(
            self.win.model.top_layer)
        for attr_name in ('name', 'side'):
            color = self.data(attr_name, COLUMNS.name, LAYER_COLOR_ROLE)
            self.assertEqual(layer_color, color.name())

    def test_the_row_header_shows_the_layer(self):
        table = self.editor.table_view
        self.editor.show()
        app.processEvents()
        header = table.verticalHeader()
        image = header.viewport().grab().toImage()
        row = self.row('side')
        y = header.sectionViewportPosition(row) + header.sectionSize(row) // 2
        color = QtGui.QColor(image.pixel(header.width() // 2, y))
        layer_color = self.win.model.get_layer_color(
            self.win.model.top_layer)
        self.assertEqual(layer_color, color.name())

    def test_off_rows_are_in_their_layers_color(self):
        from Qt import QtCore
        action = self.win.view_actions.neutral_property_text_action
        action.setChecked(False)
        self.assertIs(False, user_dir.user_prefs.get(
            user_dir.USER_PREF.NEUTRAL_PROPERTY_TEXT))
        layer = QtGui.QColor(self.win.model.get_layer_color(
            self.win.model.top_layer))
        local = self.data('name', COLUMNS.value, QtCore.Qt.ForegroundRole)
        inherited = self.data('side', COLUMNS.value, QtCore.Qt.ForegroundRole)
        self.assertEqual(layer.lighter(150).name(), local.name())
        self.assertEqual(layer.darker(150).name(), inherited.name())
        self.assertIsNone(self.data('name', COLUMNS.name,
                                    QtCore.Qt.FontRole))
        action.setChecked(True)
        self.assertIs(True, user_dir.user_prefs.get(
            user_dir.USER_PREF.NEUTRAL_PROPERTY_TEXT))


class TheRowHeader(unittest.TestCase):
    """Painting a row header asked the table's sorting proxy for the row's
    layer color, and an invalid index, from a table with rows but no
    columns yet or one part way through a reset, crashed the editor."""

    def test_rows_without_columns_do_not_crash(self):
        from Qt import QtCore
        source = QtGui.QStandardItemModel(3, 0)
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(source)
        header = property_editor.LayerRowHeader()
        header.follow(proxy)
        self.assertEqual([None, None, None], header.row_colors)

    def test_it_paints_from_colors_it_kept(self):
        from Qt import QtCore
        source = QtGui.QStandardItemModel(2, COLUMNS.comment + 1)
        source.setData(source.index(0, COLUMNS.name),
                       QtGui.QColor('#0052aa'), LAYER_COLOR_ROLE)
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(source)
        header = property_editor.LayerRowHeader()
        header.follow(proxy)
        self.assertEqual('#0052aa', header.row_colors[0].name())
        source.setData(source.index(1, COLUMNS.name),
                       QtGui.QColor('#991c24'), LAYER_COLOR_ROLE)
        self.assertEqual('#991c24', header.row_colors[1].name())


class Default(unittest.TestCase):

    def test_it_is_off_unless_turned_on(self):
        with mock.patch.object(user_dir.user_prefs, 'get',
                               side_effect=lambda k, d=None: d):
            del property_editor._neutral_text[:]
            self.assertFalse(property_editor.neutral_text())
        del property_editor._neutral_text[:]


if __name__ == '__main__':
    unittest.main()
