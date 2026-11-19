"""Sub-graph nodes in the editor.

A node that runs another graph opens it in a tab, and the Property Editor
shows that graph's parameters, its world node's attrs, that the node does
not set yet. Setting one's value sets it on the node.
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
from nxt.session import Session
from nxt_editor import stage_model, sub_graphs
from nxt_editor.dockwidgets.property_editor import (COLUMNS, LOCALITIES,
                                                    PropertyModel)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

CHILD = {'version': '1.17', 'alias': 'child', 'nodes': {
    '/': {'attrs': {'rig_name': {'value': 'bob',
                                 'comment': 'Name of the rig'},
                    'count': {'value': '3'}}},
    '/run': {'code': ['print(STAGE.rig_name)']}}}


class SubGraphTestCase(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_sub_graph_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.child = os.path.join(self.folder, 'child.nxt')
        with open(self.child, 'w') as f:
            json.dump(CHILD, f)
        self.top = os.path.join(self.folder, 'top.nxt')
        nodes = {
            '/runs_child': {'instance': '/_sub_graph', 'attrs': {
                '_graph_path': {'value': self.child.replace('\\', '/')},
                'count': {'value': '5'}}},
            '/relative': {'instance': '/_sub_graph', 'attrs': {
                '_graph_path': {'value': '"child.nxt"'}}},
            '/missing': {'instance': '/_sub_graph', 'attrs': {
                '_graph_path': {'value': 'nowhere.nxt'}}},
            '/plain': {},
        }
        with open(self.top, 'w') as f:
            json.dump({'version': '1.17', 'alias': 'top',
                       'references': ['$NXT_BUILTINS/sub_graphs.nxt'],
                       'nodes': nodes}, f)
        self.model = stage_model.StageModel(
            Session().load_file(filepath=self.top))


class GraphPath(SubGraphTestCase):

    def test_the_graph_a_node_runs(self):
        self.assertEqual(os.path.normpath(self.child),
                         sub_graphs.graph_path(self.model, '/runs_child'))

    def test_quoted_and_relative_to_the_graph(self):
        self.assertEqual(os.path.normpath(self.child),
                         sub_graphs.graph_path(self.model, '/relative'))

    def test_none_without_a_graph_there(self):
        self.assertIsNone(sub_graphs.graph_path(self.model, '/missing'))
        self.assertIsNone(sub_graphs.graph_path(self.model, '/plain'))

    def test_its_parameters(self):
        attrs = sub_graphs.world_attrs(self.child)
        self.assertEqual({'rig_name', 'count'}, set(attrs))
        self.assertEqual('Name of the rig', attrs['rig_name'][1])


class Parameters(SubGraphTestCase):

    def rows(self, node_path):
        self.view = QtWidgets.QTableView()
        model = PropertyModel(graph_model=self.model, view=self.view,
                              headers=[''] * 6)
        self.view.setModel(model)
        model.set_represented_node(node_path)
        return model, {row[COLUMNS.name]: row for row in model._data
                       if row}

    def test_ones_the_node_does_not_set_are_shown(self):
        _, rows = self.rows('/runs_child')
        self.assertEqual(LOCALITIES.sub_graph,
                         rows['rig_name'][COLUMNS.locality])
        self.assertEqual('bob', rows['rig_name'][COLUMNS.value])
        self.assertEqual(os.path.normpath(self.child),
                         rows['rig_name'][COLUMNS.source])
        # count the node sets itself, so it is its own row.
        self.assertEqual(LOCALITIES.local, rows['count'][COLUMNS.locality])

    def test_a_plain_node_has_none(self):
        _, rows = self.rows('/plain')
        self.assertFalse([row for row in rows.values()
                          if row[COLUMNS.locality] == LOCALITIES.sub_graph])

    def test_setting_one_sets_it_on_the_node(self):
        model, rows = self.rows('/runs_child')
        row = list(rows).index('rig_name')
        model.setData(model.index(row, COLUMNS.value), 'jim',
                      QtCore.Qt.EditRole)
        self.assertEqual('jim', self.model.get_node_attr_value(
            '/runs_child', 'rig_name', layer=self.model.target_layer,
            data_state=DATA_STATE.RAW))

    def test_its_name_cannot_be_edited(self):
        model, rows = self.rows('/runs_child')
        row = list(rows).index('rig_name')
        flags = model.flags(model.index(row, COLUMNS.name))
        self.assertFalse(flags & QtCore.Qt.ItemIsEditable)

    def test_clicking_its_source_opens_the_graph(self):
        model, rows = self.rows('/runs_child')
        row = list(rows).index('rig_name')
        opened = []
        model.open_graph.connect(opened.append)
        index = model.index(row, COLUMNS.source)
        model.setData(index, index.data(), QtCore.Qt.CheckStateRole)
        self.assertEqual([os.path.normpath(self.child)], opened)


class OpenSubGraph(SubGraphTestCase):

    def test_the_action_opens_it(self):
        from nxt_editor.main_window import MainWindow
        win = MainWindow(filepath=self.top)
        try:
            win.model.set_selection(['/runs_child'])
            with mock.patch.object(win, 'load_file') as load:
                win.node_actions.open_sub_graph_action.trigger()
            load.assert_called_once_with(os.path.normpath(self.child))
        finally:
            with mock.patch.object(stage_model.StageModel,
                                   'get_unsaved_changes', return_value=[]):
                win.close()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
