"""The filter field above the Property Editor's attribute table.

It shows only the attributes whose name or value has what was typed in
it, ignoring case, with * for anything and commas between terms, the way
the node searches work. Clearing it shows them all again, and it keeps
filtering as other nodes are shown.
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
from Qt import QtWidgets

# Internal
from nxt_editor import stage_model
from nxt_editor.dockwidgets.property_editor import (COLUMNS, PropertyEditor,
                                                    attr_filter_regex)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'filtering', 'color': '#0052aa',
         'nodes': {
             '/rig': {'attrs': {
                 'side': {'value': 'left'},
                 'arm_length': {'value': '12'},
                 'leg_length': {'value': '20'},
                 'label': {'value': 'Upper Arm'}}},
             '/other': {'attrs': {
                 'arm_count': {'value': '2'},
                 'mood': {'value': 'fine'}}}}}


class FilterText(unittest.TestCase):

    def test_nothing_typed_filters_nothing(self):
        self.assertIsNone(attr_filter_regex(''))
        self.assertIsNone(attr_filter_regex(' , *'))

    def test_terms(self):
        regex = attr_filter_regex('ARM*len, mood')
        self.assertTrue(regex.search('arm_length'))
        self.assertTrue(regex.search('mood'))
        self.assertFalse(regex.search('leg_length'))

    def test_other_characters_are_matched_as_typed(self):
        regex = attr_filter_regex('a.b')
        self.assertTrue(regex.search('a.b'))
        self.assertFalse(regex.search('axb'))


class TheFilterField(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_filter_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'filtering.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.win.model.set_selection(['/rig'])
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

    def shown(self):
        view_model = self.editor.table_view.model()
        names = set()
        for row in range(view_model.rowCount()):
            names.add(view_model.index(row, COLUMNS.name).data())
        return names

    def test_the_field_sits_above_the_table(self):
        field = self.editor.attr_filter_field
        self.assertTrue(field.isVisible())
        self.assertTrue(field.isClearButtonEnabled())
        self.assertLess(field.mapTo(self.editor, field.rect().bottomLeft()).y(),
                        self.editor.table_view.mapTo(self.editor,
                                                     self.editor.table_view
                                                     .rect().topLeft()).y())

    def test_typing_filters_by_name_ignoring_case(self):
        self.assertEqual(self.shown(), {'side', 'arm_length', 'leg_length',
                                        'label'})
        self.editor.attr_filter_field.setText('LENGTH')
        self.assertEqual(self.shown(), {'arm_length', 'leg_length'})

    def test_values_match_too(self):
        self.editor.attr_filter_field.setText('upper')
        self.assertEqual(self.shown(), {'label'})

    def test_wildcards_and_commas(self):
        self.editor.attr_filter_field.setText('a*len, side')
        self.assertEqual(self.shown(), {'arm_length', 'side'})

    def test_clearing_shows_everything_again(self):
        self.editor.attr_filter_field.setText('side')
        self.editor.attr_filter_field.clear()
        self.assertEqual(len(self.shown()), 4)

    def test_the_filter_stays_on_another_node(self):
        self.editor.attr_filter_field.setText('arm')
        self.win.model.set_selection(['/other'])
        app.processEvents()
        self.assertEqual(self.shown(), {'arm_count'})

    def test_selected_attrs_are_read_through_the_filter(self):
        self.editor.attr_filter_field.setText('leg')
        self.editor.table_view.selectRow(0)
        self.assertEqual(self.editor.get_selected_attr_names(),
                         {'leg_length'})


if __name__ == '__main__':
    unittest.main()
