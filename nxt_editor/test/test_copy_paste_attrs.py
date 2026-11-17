"""Copying attributes from one node and pasting them onto others.

Copy Attributes puts the selected attributes on the clipboard as JSON,
each with its name, raw value, type and comment. Paste Attributes adds
them to every selected node on the target layer, or sets them where a
node already has them, as one undo. Both are in the attribute table's
right click menu and have hotkeys, Ctrl+C and Ctrl+V, while the Property
Editor has focus. Copying a value alone, raw, resolved or cached, is still
there as well.
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
from Qt import QtCore, QtWidgets
from Qt.QtTest import QTest

# Internal
from nxt import DATA_STATE
from nxt_editor import stage_model
from nxt_editor.dockwidgets.property_editor import COLUMNS, PropertyEditor

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'attrs', 'color': '#0052aa',
         'nodes': {
             '/rig': {'attrs': {
                 'side': {'value': 'left', 'comment': 'which side'},
                 'count': {'value': '3'},
                 'other': {'value': 'not copied'}}},
             '/a': {'attrs': {'count': {'value': '1'}}},
             '/b': {}}}


class CopyPasteAttrs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_attr_copy_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'attrs.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.model = self.win.model
        self.select('/rig')
        self.editor = self.win.findChild(PropertyEditor)
        QtWidgets.QApplication.clipboard().setText('')

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def select(self, *node_paths):
        self.model.set_selection(list(node_paths))
        app.processEvents()

    def select_attrs(self, *attr_names):
        table = self.editor.table_view
        view_model = table.model()
        table.clearSelection()
        flags = (QtCore.QItemSelectionModel.Select |
                 QtCore.QItemSelectionModel.Rows)
        for row in range(view_model.rowCount()):
            index = view_model.index(row, COLUMNS.name)
            if index.data() in attr_names:
                table.selectionModel().select(index, flags)

    def clipboard(self):
        return json.loads(QtWidgets.QApplication.clipboard().text())

    def value(self, node_path, attr_name):
        return self.model.get_node_attr_value(node_path, attr_name,
                                              self.model.comp_layer,
                                              data_state=DATA_STATE.RAW)

    def test_copy_puts_names_values_types_and_comments_on_the_clipboard(self):
        self.select_attrs('side', 'count')
        self.editor.copy_attrs_action.trigger()
        attrs = self.clipboard()[self.model.ATTRS_CLIPBOARD_KEY]
        by_name = {attr['name']: attr for attr in attrs}
        self.assertEqual(set(by_name), {'side', 'count'})
        self.assertEqual(by_name['side']['value'], 'left')
        self.assertEqual(by_name['side']['comment'], 'which side')
        self.assertEqual(by_name['count']['value'], '3')
        self.assertEqual(by_name['count']['type'], 'int')

    def test_paste_onto_every_selected_node_is_one_undo(self):
        self.select_attrs('side', 'count')
        self.editor.copy_attrs_action.trigger()
        self.select('/a', '/b')
        undo_count = self.model.undo_stack.count()
        self.editor.paste_attrs_action.trigger()
        app.processEvents()
        for node_path in ('/a', '/b'):
            self.assertEqual(self.value(node_path, 'side'), 'left')
            self.assertEqual(self.value(node_path, 'count'), '3')
            self.assertEqual(self.model.get_node_attr_comment(
                node_path, 'side', self.model.comp_layer), 'which side')
            self.assertFalse(self.value(node_path, 'other'))
        self.assertEqual(self.model.undo_stack.count(), undo_count + 1)
        self.model.undo()
        self.assertEqual(self.value('/a', 'count'), '1',
                         'undo should put back what /a had')
        self.assertNotIn('side', self.model.get_node_local_attr_names(
            '/b', self.model.comp_layer))

    def test_paste_goes_on_the_target_layer(self):
        self.select_attrs('count')
        self.editor.copy_attrs_action.trigger()
        self.select('/b')
        self.editor.paste_attrs_action.trigger()
        target = self.model.target_layer
        self.assertEqual(self.model.get_node_attr_value(
            '/b', 'count', target, data_state=DATA_STATE.RAW), '3')

    def test_paste_ignores_other_text(self):
        QtWidgets.QApplication.clipboard().setText('just some text')
        self.select('/b')
        undo_count = self.model.undo_stack.count()
        self.editor.paste_attrs_action.trigger()
        self.assertEqual(self.model.undo_stack.count(), undo_count)
        QtWidgets.QApplication.clipboard().setText('[{"/n": {}}]')
        self.editor.paste_attrs_action.trigger()
        self.assertEqual(self.model.undo_stack.count(), undo_count)

    def test_copying_a_value_alone_still_works(self):
        self.select_attrs('count')
        self.editor.copy_raw_action.trigger()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), '3')

    def test_they_are_in_the_hotkey_editor(self):
        rows = self.win.get_hotkey_map()['Property Editor']
        shortcuts = {row[0]: row[3] for row in rows}
        self.assertEqual(shortcuts.get('Copy Attributes'), 'Ctrl+C')
        self.assertEqual(shortcuts.get('Paste Attributes'), 'Ctrl+V')

    def test_the_hotkeys_work_from_the_table(self):
        self.win.activateWindow()
        QtWidgets.QApplication.setActiveWindow(self.win)
        table = self.editor.table_view
        table.setFocus()
        app.processEvents()
        self.select_attrs('side')
        QTest.keyClick(table, QtCore.Qt.Key_C, QtCore.Qt.ControlModifier)
        app.processEvents()
        attrs = self.clipboard()[self.model.ATTRS_CLIPBOARD_KEY]
        self.assertEqual([attr['name'] for attr in attrs], ['side'])
        self.select('/b')
        table.setFocus()
        app.processEvents()
        QTest.keyClick(table, QtCore.Qt.Key_V, QtCore.Qt.ControlModifier)
        app.processEvents()
        self.assertEqual(self.value('/b', 'side'), 'left')


if __name__ == '__main__':
    unittest.main()
