"""Every edit to a layer shows on the layer, as it happens.

The layer view stripes a layer with unsaved changes. Taking something off a
node, such as a local attribute, left the layer looking saved: removing an
attribute runs the add attribute command backwards, and the bookkeeping that
decides whether a layer has changed ran backwards with it, so the layer was
marked and then unmarked again in the same edit. Reverting a node's exec
input did not even do the revert. Each edit here starts from a layer just
loaded from disk and checks the layer has changed, that undo takes it back
to saved, and that redo changes it again.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

BASE = {
    'version': '1.17', 'alias': 'base',
    'nodes': {
        '/src': {'attrs': {'shared': {'value': '1'}},
                 'code': ['x = 1']},
        '/a': {'attrs': {'shared': {'value': '1'}}},
        '/b': {},
    },
}
TOP = {
    'version': '1.17', 'alias': 'top', 'references': ['./base.nxt'],
    'nodes': {
        '/a': {'attrs': {'shared': {'value': '2'},
                         'mine': {'value': '3'}},
               'code': ['print("mine")'],
               'comment': 'a comment',
               'instance': '/src',
               'execute_in': '/b',
               'enabled': False,
               'child_order': ['c']},
        '/a/c': {},
        '/b': {'attrs': {'other': {'value': '4'}}},
    },
}


class LayerEditsShow(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, data in (('base.nxt', BASE), ('top.nxt', TOP)):
            with open(os.path.join(self.tmp, name), 'w') as fp:
                json.dump(data, fp)
        self.stage = Session().load_file(
            filepath=os.path.join(self.tmp, 'top.nxt'))
        self.model = stage_model.StageModel(self.stage)
        self.top = self.model.top_layer.real_path
        self.signals = []
        self.model.effected_layers.signal.connect(self.signals.append)
        self.assertEqual(set(), set(self.model.effected_layers))

    def check_edit(self, edit):
        stack = self.model.undo_stack
        edit()
        self.assertTrue(stack.count(), 'the edit did nothing')
        self.assertIn(self.top, self.model.effected_layers,
                      'the layer still looks saved after the edit')
        self.assertIn(self.top, self.signals,
                      'the layer view was not told the layer changed')
        while stack.canUndo():
            stack.undo()
        self.assertNotIn(self.top, self.model.effected_layers,
                         'undoing it all left the layer looking changed')
        while stack.canRedo():
            stack.redo()
        self.assertIn(self.top, self.model.effected_layers,
                      'redoing it left the layer looking saved')

    def local_attrs(self, path):
        return self.model.get_node_local_attr_names(path, self.model.top_layer)

    # Taking things off a node

    def test_deleting_an_attribute(self):
        self.check_edit(lambda: self.model.delete_node_attr('/a', 'mine'))
        self.assertNotIn('mine', self.local_attrs('/a'))

    def test_reverting_attributes(self):
        self.check_edit(lambda: self.model.revert_node_attrs(
            '/a', ['shared', 'mine']))
        self.assertNotIn('mine', self.local_attrs('/a'))
        self.assertNotIn('shared', self.local_attrs('/a'))

    def test_reverting_code(self):
        self.check_edit(lambda: self.model.revert_node_code('/a'))

    def test_reverting_the_instance(self):
        self.check_edit(lambda: self.model.revert_node_instance('/a'))

    def test_reverting_the_exec_input(self):
        self.check_edit(lambda: self.model.revert_node_in_exec_source('/a'))
        self.assertFalse(self.model.get_node_exec_in('/a'))

    def test_reverting_enabled(self):
        self.check_edit(lambda: self.model.revert_node_enabled(['/a']))

    def test_reverting_the_child_order(self):
        self.check_edit(lambda: self.model.revert_child_order('/a'))

    def test_reverting_a_node(self):
        self.check_edit(lambda: self.model.revert_nodes(
            ['/b'], layer=self.model.top_layer))

    def test_deleting_a_node(self):
        self.check_edit(lambda: self.model.delete_nodes(['/b']))

    def test_undoing_a_saved_delete_changes_the_layer_again(self):
        self.model.delete_node_attr('/a', 'mine')
        # What saving does in the editor.
        self.model.effected_layers.remove(self.top)
        self.model.layer_saved.emit(self.top)
        self.model.undo_stack.undo()
        self.assertIn(self.top, self.model.effected_layers)
        self.model.undo_stack.redo()
        self.assertNotIn(self.top, self.model.effected_layers)

    # Putting things on a node, which already showed

    def test_adding_an_attribute(self):
        self.check_edit(lambda: self.model.add_node_attr('/b', 'new', '5'))

    def test_setting_an_attribute(self):
        self.check_edit(lambda: self.model.set_node_attr_value(
            '/a', 'mine', '9'))

    def test_localizing_an_attribute(self):
        self.check_edit(lambda: self.model.localize_node_attrs(
            '/b', ['shared']))

    def test_the_other_node_edits(self):
        edits = {
            'code': lambda model: model.set_node_code_lines('/b', ['y = 2']),
            'comment': lambda model: model.set_node_comment('/b', 'hello'),
            'instance': lambda model: model.set_node_instance('/b', '/src'),
            'exec input': lambda model: model.set_node_exec_in('/b', '/a'),
            'enabled': lambda model: model.set_node_enabled(['/b'], False),
            'start point': lambda model: model.set_startpoints(['/b'], True),
            'name': lambda model: model.set_node_name('/b', 'renamed'),
            'parent': lambda model: model.parent_nodes(['/b'], '/a'),
            'position': lambda model: model.set_nodes_pos({'/b': (50.0, 50.0)}),
            'duplicate': lambda model: model.duplicate_nodes(['/b']),
            'localize': lambda model: model.localize_nodes(['/src']),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.setUp()
                self.check_edit(lambda: edit(self.model))

    def test_renaming_an_attribute(self):
        self.check_edit(lambda: self.model.rename_node_attr(
            '/a', 'mine', 'yours'))


if __name__ == '__main__':
    unittest.main()
