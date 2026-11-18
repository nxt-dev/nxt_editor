"""The Cached view shows where running the graph changed a type.

A compute can leave an attribute a different type than the graph gives
it. In the Cached view the Property Editor highlights that attribute's
type and says what it was in a tooltip, "was list, now raw". Attributes
the compute left alone, and the Raw and Resolved views, are unmarked.
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

# Internal
from nxt import DATA_STATE
from nxt_editor import colors, stage_model
from nxt_editor.dockwidgets.property_editor import COLUMNS, PropertyEditor

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'types', 'color': '#0052aa',
         'nodes': {
             '/node': {'attrs': {'items': {'value': '[1, 2]'},
                                 'count': {'value': '5'},
                                 'name': {'value': 'abc'}},
                       'code': ['self.items = "now a string"',
                                'self.count = 6',
                                'self.made_here = [1]']}}}


class TypeChanges(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_type_changes_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'types.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.model = self.win.model
        self.model.execute_nodes(['/node'])
        self.model.set_selection(['/node'])
        app.processEvents()
        self.editor = self.win.findChild(PropertyEditor)
        self.table_model = self.editor.model

    def tearDown(self):
        self.model.data_state = DATA_STATE.RAW
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def type_index(self, attr_name):
        model = self.table_model
        for row in range(model.rowCount(None)):
            if model.data(model.index(row, COLUMNS.name)) == attr_name:
                return model.index(row, COLUMNS.nxt_type)
        self.fail(attr_name + ' is not in the table')

    def view(self, state):
        self.model.data_state = state
        app.processEvents()

    def test_a_changed_type_is_highlighted_with_what_it_was(self):
        self.view(DATA_STATE.CACHED)
        index = self.type_index('items')
        self.assertEqual(self.table_model.data(index, QtCore.Qt.ToolTipRole),
                         'was list, now raw')
        brush = self.table_model.data(index, QtCore.Qt.BackgroundRole)
        self.assertIsNotNone(brush, 'the changed type is not highlighted')
        self.assertEqual(brush.color(), colors.TYPE_CHANGED)

    def test_a_new_value_of_the_same_type_is_not(self):
        self.view(DATA_STATE.CACHED)
        index = self.type_index('count')
        self.assertIsNone(self.table_model.data(index,
                                                QtCore.Qt.BackgroundRole))
        self.assertFalse(self.table_model.data(index,
                                               QtCore.Qt.ToolTipRole))

    def test_untouched_and_compute_made_attrs_are_not(self):
        self.view(DATA_STATE.CACHED)
        for attr_name in ('name', 'made_here'):
            index = self.type_index(attr_name)
            self.assertIsNone(self.table_model.data(
                index, QtCore.Qt.BackgroundRole), attr_name)

    def test_only_in_the_cached_view(self):
        for state in (DATA_STATE.RAW, DATA_STATE.RESOLVED):
            self.view(state)
            index = self.type_index('items')
            self.assertIsNone(self.table_model.data(
                index, QtCore.Qt.BackgroundRole), state)
            self.assertFalse(self.table_model.data(index,
                                                   QtCore.Qt.ToolTipRole))


if __name__ == '__main__':
    unittest.main()
