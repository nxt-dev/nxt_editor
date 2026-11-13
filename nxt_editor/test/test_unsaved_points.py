"""Break and skip points on a graph that has not been saved yet.

They are kept in the user's prefs by the graph's file. Before it has one
they are kept for the session, and go to the prefs when it is first saved.
"""
# Builtin
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import user_dir
from nxt_editor.stage_model import StageModel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def forget(layer_path):
    for prefs in (user_dir.breakpoints, user_dir.skippoints):
        if layer_path in prefs:
            prefs.pop(layer_path)


class UnsavedPoints(unittest.TestCase):

    def setUp(self):
        stage = Session().new_file()
        self.model = StageModel(stage)
        self.model.add_node(name='node', pos=[0, 0])
        self.node = sorted(self.model.comp_layer.descendants())[0]
        self.assertIsNone(self.model.top_layer.real_path)

    def test_a_breakpoint_toggles(self):
        self.model.set_breakpoints([self.node])
        self.assertTrue(self.model.get_is_node_breakpoint(self.node))
        self.model.set_breakpoints([self.node])
        self.assertFalse(self.model.get_is_node_breakpoint(self.node))

    def test_a_breakpoint_undoes(self):
        self.model.set_breakpoints([self.node])
        self.model.undo_stack.undo()
        self.assertFalse(self.model.get_is_node_breakpoint(self.node))
        self.model.undo_stack.redo()
        self.assertTrue(self.model.get_is_node_breakpoint(self.node))

    def test_clearing_breakpoints(self):
        self.model.set_breakpoints([self.node])
        self.model.clear_breakpoints()
        self.assertFalse(self.model.get_is_node_breakpoint(self.node))
        self.model.undo_stack.undo()
        self.assertTrue(self.model.get_is_node_breakpoint(self.node))

    def test_a_skip_point_toggles(self):
        self.model.toggle_skippoints([self.node])
        self.assertTrue(self.model.is_node_skippoint(self.node))
        self.model.undo_stack.undo()
        self.assertFalse(self.model.is_node_skippoint(self.node))
        self.model.toggle_descendant_skips([self.node])
        self.assertTrue(self.model.is_node_skippoint(self.node))

    def test_nothing_is_written_to_the_prefs(self):
        self.model.set_breakpoints([self.node])
        self.model.toggle_skippoints([self.node])
        self.assertNotIn(None, user_dir.breakpoints)
        self.assertNotIn(None, user_dir.skippoints)

    def test_saving_keeps_them(self):
        self.model.set_breakpoints([self.node])
        self.model.toggle_skippoints([self.node])
        tmp = tempfile.mkdtemp(prefix='nxt_points_')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, 'points.nxt').replace(os.sep, '/')
        self.model.top_layer.save(path)
        self.addCleanup(forget, self.model.top_layer.real_path)
        self.model.layer_saved.emit(self.model.top_layer.real_path)
        path = self.model.top_layer.real_path
        self.assertEqual([self.node], user_dir.breakpoints.get(path))
        self.assertEqual([self.node], user_dir.skippoints.get(path))
        self.assertTrue(self.model.get_is_node_breakpoint(self.node))
        self.assertTrue(self.model.is_node_skippoint(self.node))


if __name__ == '__main__':
    unittest.main()
