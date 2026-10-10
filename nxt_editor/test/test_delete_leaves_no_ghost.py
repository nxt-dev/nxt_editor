"""Deleting a node tells the build view, so it does not leave a ghost.

DeleteNode emitted nodes_changed, which the graph listens to, but the
build view refreshes on comp_layer_changed. So a deleted node vanished
from the graph and stayed in the build, a ghost of something that no
longer existed on any layer.

This tests the model rather than the window: the build view's refresh is
wired to comp_layer_changed, so the question is whether deleting emits it.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class DeleteLeavesNoGhost(unittest.TestCase):

    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="StageInstanceTest.nxt")
        self.model = stage_model.StageModel(self.stage)
        self.comp_changes = []
        self.model.comp_layer_changed.connect(self.comp_changes.append)

    def exec_order(self, start):
        """What the build view would list for a start point."""
        return list(self.model.comp_layer.get_exec_order(start))

    def test_delete_tells_the_build_view(self):
        self.model.delete_nodes(['/inst_source1'])
        self.assertTrue(self.comp_changes,
                        'nothing emitted comp_layer_changed, so the build '
                        'view never refreshes and keeps the deleted node')

    def test_the_node_leaves_the_exec_order(self):
        # Asked from a start that survives the delete. Asking from the
        # deleted node itself is asking for the order from somewhere that
        # no longer exists.
        start = '/inst_source4'
        if self.model.comp_layer.lookup(start) is None:
            self.skipTest('this graph has no second start to ask from')
        self.assertIn('/inst_source1', self.exec_order('/inst_source1'),
                      'nothing to prove if it was not in the build')
        self.model.delete_nodes(['/inst_source1'])
        for path in self.exec_order(start):
            self.assertFalse(path.startswith('/inst_source1'),
                             '%s is still in the build' % path)

    def test_it_is_gone_from_every_layer(self):
        self.model.delete_nodes(['/inst_source1'])
        self.assertIsNone(self.model.comp_layer.lookup('/inst_source1'))
        self.assertIsNone(self.model.top_layer.lookup('/inst_source1'))

    def test_it_is_not_left_implied(self):
        # An implied node is what draws as a ghost: a path with no node of
        # its own that something still hangs off.
        self.model.delete_nodes(['/inst_source1'])
        self.assertFalse(self.model.node_is_implied('/inst_source1'))

    def test_undo_brings_it_back(self):
        before = self.exec_order('/inst_source1')
        self.model.delete_nodes(['/inst_source1'])
        self.model.undo_stack.undo()
        self.assertIsNotNone(self.model.comp_layer.lookup('/inst_source1'))
        self.assertEqual(before, self.exec_order('/inst_source1'),
                         'undo did not restore the build')

    def test_deleting_a_child_leaves_the_parent(self):
        child = '/inst_source1/inst_source1_child'
        if self.model.comp_layer.lookup(child) is None:
            self.skipTest('this graph has no such child')
        self.model.delete_nodes([child])
        self.assertIsNone(self.model.comp_layer.lookup(child))
        self.assertIsNotNone(self.model.comp_layer.lookup('/inst_source1'),
                             'deleting a child took the parent with it')


if __name__ == '__main__':
    unittest.main()
