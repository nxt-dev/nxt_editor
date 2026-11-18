"""Node paths and tokens complete in the Property Editor.

The instance path field offers every node path but the node's own, and
the exec input field every other root node, matching anywhere in the path
and ignoring case. Attribute values complete ${ tokens the way the code
editor does, from the same source: ${ offers the node's attributes and
the token prefixes, ${/ every node path, and ${/some/node. that node's
attributes as whole tokens.
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
from nxt_editor.dockwidgets import code_completion
from nxt_editor.dockwidgets.property_editor import (COLUMNS, PropertyEditor,
                                                    TokenLineEdit)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'paths', 'color': '#0052aa',
         'nodes': {
             '/rig': {'attrs': {'side': {'value': 'left'},
                                'size': {'value': '2'}}},
             '/rig/arm': {'attrs': {'length': {'value': '3'}}},
             '/export': {'attrs': {'out_dir': {'value': 'C'}}}}}


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_pe_complete_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'paths.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.model = self.win.model
        self.model.set_selection(['/rig'])
        app.processEvents()
        self.editor = self.win.findChild(PropertyEditor)

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()


class PathFields(Base):

    def offered(self, completer, typed):
        completer.setCompletionPrefix(typed)
        found = []
        model = completer.completionModel()
        for row in range(model.rowCount()):
            found.append(model.index(row, 0).data())
        return found

    def test_instance_offers_every_other_node_path(self):
        self.editor.focus_instance_field(True)
        completer = self.editor.instance_field.completer()
        self.assertEqual(self.offered(completer, ''), ['/export', '/rig/arm'])

    def test_paths_match_anywhere_ignoring_case(self):
        self.editor.focus_instance_field(True)
        completer = self.editor.instance_field.completer()
        self.assertEqual(self.offered(completer, 'ARM'), ['/rig/arm'])

    def test_exec_input_offers_other_root_nodes(self):
        self.editor.focus_execute_field(True)
        completer = self.editor.execute_field.completer()
        self.assertEqual(self.offered(completer, ''), ['/export'])

    def test_a_node_added_since_is_offered_on_focus(self):
        # Quietly, so the only thing to pick it up is the field's focus.
        self.model.blockSignals(True)
        try:
            self.model.add_node(name='late', parent_path='/')
        finally:
            self.model.blockSignals(False)
        self.assertEqual(self.editor.node_path, '/rig')
        self.editor.focus_instance_field(True)
        completer = self.editor.instance_field.completer()
        self.assertIn('/late', self.offered(completer, 'late'))


class TokenValues(Base):

    def make_edit(self, node_path='/rig'):
        edit = TokenLineEdit(self.model, node_path)
        self.addCleanup(edit.deleteLater)
        edit.show()
        return edit

    def type_into(self, edit, text):
        QTest.keyClicks(edit, text)
        app.processEvents()

    def offered(self, edit):
        found = []
        model = edit.completer.completionModel()
        for row in range(model.rowCount()):
            found.append(model.index(row, 0).data())
        return found

    def test_values_edit_in_a_token_line_edit(self):
        table = self.editor.table_view
        view_model = table.model()
        index = view_model.index(0, COLUMNS.value)
        delegate = table.itemDelegateForColumn(COLUMNS.value)
        editor = delegate.createEditor(table.viewport(),
                                       QtWidgets.QStyleOptionViewItem(),
                                       index)
        self.addCleanup(editor.deleteLater)
        self.assertIsInstance(editor, TokenLineEdit)
        self.assertEqual(editor.node_path, '/rig')

    def test_completing_in_the_table_and_committing(self):
        self.win.activateWindow()
        table = self.editor.table_view
        view_model = table.model()
        row = [r for r in range(view_model.rowCount())
               if view_model.index(r, COLUMNS.name).data() == 'side'][0]
        table.setFocus()
        table.edit(view_model.index(row, COLUMNS.value))
        app.processEvents()
        edit = table.findChild(TokenLineEdit)
        self.assertIsNotNone(edit, 'no value editor opened')
        edit.clear()
        self.type_into(edit, '${si')
        popup = edit.completer.popup()
        self.assertTrue(popup.isVisible())
        # Picked the way the popup reports a choice. On macOS a Return
        # pressed on the popup in a test also reaches the cell editor,
        # which then commits and closes before it can be looked at.
        index = popup.model().index(1, 0)
        popup.setCurrentIndex(index)
        edit.completer.activated[str].emit(index.data())
        app.processEvents()
        self.assertEqual(edit.text(), '${size}')
        self.assertTrue(edit.isVisible(),
                        'choosing a completion closed the editor')
        QTest.keyClick(edit, QtCore.Qt.Key_Return)
        app.processEvents()
        value = self.model.get_node_attr_value('/rig', 'side',
                                               self.model.comp_layer,
                                               data_state=DATA_STATE.RAW)
        self.assertEqual(value, '${size}')

    def test_dollar_brace_offers_the_nodes_attributes(self):
        edit = self.make_edit()
        self.type_into(edit, 'a ${si')
        self.assertTrue(edit.completer.popup().isVisible())
        self.assertEqual(self.offered(edit), ['${side}', '${size}'])

    def test_node_paths_inside_a_token(self):
        edit = self.make_edit()
        self.type_into(edit, '${/')
        self.assertEqual(self.offered(edit),
                         ['${/export', '${/rig', '${/rig/arm'])

    def test_another_nodes_attributes_after_its_dot(self):
        edit = self.make_edit()
        self.type_into(edit, '${/rig/arm.')
        # Its own, then what it inherits from /rig.
        self.assertEqual(self.offered(edit), ['${/rig/arm.length}',
                                              '${/rig/arm.side}',
                                              '${/rig/arm.size}'])

    def test_choosing_one_replaces_only_the_typed_token(self):
        edit = self.make_edit()
        self.type_into(edit, 'x ${/rig/arm.le')
        popup = edit.completer.popup()
        self.assertTrue(popup.isVisible())
        QTest.keyClick(popup, QtCore.Qt.Key_Return)
        app.processEvents()
        self.assertEqual(edit.text(), 'x ${/rig/arm.length}')

    def test_no_token_no_popup(self):
        edit = self.make_edit()
        self.type_into(edit, 'plain words')
        self.assertFalse(edit.completer.popup().isVisible())

    def test_same_source_as_the_code_editor(self):
        self.assertEqual(code_completion.token_completions(self.model,
                                                           '${/export.'),
                         ['${/export.out_dir}'])


if __name__ == '__main__':
    unittest.main()
