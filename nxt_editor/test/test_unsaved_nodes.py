"""Nodes with changes that are not saved yet are known, and drawn so.

The Layer Manager says a layer has unsaved changes, but not which nodes
they are on. Each command notes the nodes it changes, by layer, and a node
has unsaved changes on a layer when a command that changed it there lies
between where the layer was last saved and where the undo stack is now.
Undoing back to the save clears it; undoing past the save marks it again.
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
from nxt_editor.main_window import MainWindow
from nxt_editor.node_graphics_item import NodeGraphicsItem

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(path, alias, nodes, references=()):
    with open(path, 'w') as file_object:
        json.dump({'version': '1.17', 'alias': alias,
                   'references': list(references),
                   'nodes': {n: {} for n in nodes}}, file_object)
    return path


class UnsavedNodes(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_unsaved_'))
        write_graph(os.path.join(self.tmp, 'ref.nxt'), 'ref', ['/r'])
        self.path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                ['/a', '/b', '/c'], ['ref.nxt'])
        self.model = stage_model.StageModel(Session().load_file(self.path))
        self.top = self.model.top_layer.real_path
        self.ref = self.model.stage._sub_layers[1].real_path
        self.changed = []
        self.model.unsaved_nodes_changed.connect(self.changed.append)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def unsaved(self, layer_path=None):
        return self.model.unsaved_node_paths(layer_path)

    def edit(self, node_path, value=1):
        self.model.set_node_attr_value(node_path, 'x', value)

    def save(self, layer_path=None):
        # What the window does once a layer is written.
        self.model.layer_saved.emit(layer_path or self.top)

    def test_nothing_is_unsaved_when_opened(self):
        self.assertEqual(set(), self.unsaved())

    def test_an_edit_marks_the_node(self):
        self.edit('/a')
        self.assertEqual({'/a'}, self.unsaved(self.top))
        self.assertIn(('/a',), self.changed)

    def test_undo_unmarks_and_redo_marks_again(self):
        self.edit('/a')
        self.model.undo()
        self.assertEqual(set(), self.unsaved())
        self.model.redo()
        self.assertEqual({'/a'}, self.unsaved())

    def test_saving_clears_it(self):
        self.edit('/a')
        self.save()
        self.assertEqual(set(), self.unsaved())

    def test_undoing_past_a_save_marks_it_again(self):
        self.edit('/a')
        self.save()
        self.model.undo()
        self.assertEqual({'/a'}, self.unsaved())
        self.model.redo()
        self.assertEqual(set(), self.unsaved())

    def test_an_undone_change_thrown_away_stays_marked(self):
        self.edit('/a')
        self.save()
        self.model.undo()
        # This throws the edit to /a away, so what is saved can no longer
        # be undone back to.
        self.edit('/b')
        self.assertEqual({'/a', '/b'}, self.unsaved())
        self.model.undo()
        self.assertEqual({'/a'}, self.unsaved())
        self.save()
        self.assertEqual(set(), self.unsaved())

    def test_layers_are_kept_apart(self):
        self.edit('/a')
        self.model.set_target_layer(self.ref)
        self.model.set_node_attr_value('/r', 'y', 2)
        self.assertEqual({'/a'}, self.unsaved(self.top))
        self.assertEqual({'/r'}, self.unsaved(self.ref))
        self.save(self.top)
        self.assertEqual({'/r'}, self.unsaved())
        self.assertEqual([self.ref], self.model.get_node_unsaved_layers('/r'))

    def test_commands_in_a_macro_count(self):
        self.model.set_nodes_pos({'/a': (0, 0), '/b': (0, 100)})
        self.model.undo_stack.beginMacro('several')
        self.edit('/a')
        self.edit('/c')
        self.model.undo_stack.endMacro()
        self.assertEqual({'/a', '/b', '/c'}, self.unsaved())
        self.model.undo()
        self.assertEqual({'/a', '/b'}, self.unsaved())

    def test_a_renamed_node_is_marked_by_its_new_name(self):
        self.model.set_node_name('/a', 'renamed')
        self.assertIn('/renamed', self.unsaved())

    def test_reloading_a_layer_clears_it(self):
        self.edit('/a')
        self.model.reload_layers([self.top])
        self.assertEqual(set(), self.unsaved())


class UnsavedNodesInTheGraph(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_unsaved_ui_'))
        self.path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                ['/a', '/b'])
        self.win = MainWindow(filepath=self.path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model

    def tearDown(self):
        self.model.effected_layers.clear()
        self.win.hide()
        app.processEvents()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def items(self):
        return {i.node_path: i for i in self.win.view.scene().items()
                if isinstance(i, NodeGraphicsItem)}

    def test_the_node_shows_it_until_saved(self):
        self.model.set_node_attr_value('/a', 'x', 1)
        app.processEvents()
        items = self.items()
        self.assertTrue(items['/a'].has_unsaved_changes())
        self.assertFalse(items['/b'].has_unsaved_changes())
        self.win.save_layer(self.model.top_layer)
        app.processEvents()
        self.assertFalse(items['/a'].has_unsaved_changes())


if __name__ == '__main__':
    unittest.main()
