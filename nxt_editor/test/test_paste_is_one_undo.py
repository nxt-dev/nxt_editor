"""Pasting nodes is one edit, and it says so afterwards.

Paste added a node at a time, each one its own entry on the undo stack, so
taking back a paste of three nodes took three undos and the two states in
between were graphs nobody had ever asked for.

Undoing it was quiet in the other direction too. Adding and removing a
node announces nodes changing, but the build view and the workflow tools
listen for the comp changing, so they carried on describing nodes that had
just been put back or taken away.
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

COPY_ME = ['/inst_source1', '/inst_source2', '/inst_source4']


class Pasteboard(object):
    """Stands in for the system clipboard.

    The real one needs a running event loop before it hands text back,
    and asking it for text it was just given returns nothing often enough
    to make a run of these tests pass or fail on the weather. What a
    paste does to a graph is the thing under test here, not Windows.
    """

    def __init__(self):
        self._text = ''

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class PastingNodes(unittest.TestCase):

    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="StageInstanceTest.nxt")
        self.model = stage_model.StageModel(self.stage)
        self.model.clipboard = Pasteboard()
        self.comp_changes = []
        self.model.comp_layer_changed.connect(self.comp_changes.append)

    def pasted(self):
        return sorted(p for p in self.model.comp_layer.descendants()
                      if '_pasted' in p)

    def copy_and_paste(self, node_paths=COPY_ME):
        self.model.copy_nodes(node_paths)
        return self.model.paste_nodes(pos=[0.0, 0.0])

    def test_a_paste_of_several_nodes_is_one_undo(self):
        self.copy_and_paste()
        self.assertEqual(1, self.model.undo_stack.count(),
                         'each pasted node went on the undo stack by '
                         'itself, so one undo only takes back part of it')

    def test_one_undo_takes_the_whole_paste_back(self):
        before = sorted(self.model.comp_layer.descendants())
        self.copy_and_paste()
        self.assertEqual(3, len(self.pasted()))
        self.model.undo_stack.undo()
        self.assertEqual([], self.pasted())
        self.assertEqual(before, sorted(self.model.comp_layer.descendants()))

    def test_redo_brings_the_whole_paste_back(self):
        self.copy_and_paste()
        was_pasted = self.pasted()
        self.model.undo_stack.undo()
        self.model.undo_stack.redo()
        self.assertEqual(was_pasted, self.pasted())

    def test_the_paste_tells_the_build_view(self):
        del self.comp_changes[:]
        self.copy_and_paste()
        self.assertTrue(self.comp_changes,
                        'nothing emitted comp_layer_changed, so the build '
                        'view and the workflow tools do not know the '
                        'pasted nodes are there')

    def test_undoing_the_paste_tells_it_too(self):
        self.copy_and_paste()
        del self.comp_changes[:]
        self.model.undo_stack.undo()
        self.assertTrue(self.comp_changes,
                        'undo left the build view listing nodes that are '
                        'no longer in the graph')

    def test_the_pasted_nodes_are_what_is_selected(self):
        pasted = self.copy_and_paste()
        self.assertEqual(sorted(pasted), sorted(self.model.selection))

    def test_pasting_one_node_is_still_named_after_it(self):
        # A single node does not need wrapping up, and wrapping it would
        # only bury what was pasted under a macro nobody asked for.
        pasted = self.copy_and_paste(['/inst_source1'])
        self.assertEqual(1, len(pasted))
        self.assertIn(pasted[0], self.model.undo_stack.text(0))

    def test_pasting_nothing_leaves_the_undo_stack_alone(self):
        self.model.clipboard.setText('not a graph')
        self.assertEqual([], self.model.paste_nodes(pos=[0.0, 0.0]))
        self.assertEqual(0, self.model.undo_stack.count())

    def test_adding_a_node_tells_the_build_view(self):
        del self.comp_changes[:]
        self.model.add_node(name='fresh', layer=self.model.top_layer)
        self.assertTrue(self.comp_changes,
                        'a new node can be a start point, and the build '
                        'view never heard about it')

    def test_undoing_a_new_node_tells_it_as_well(self):
        self.model.add_node(name='fresh', layer=self.model.top_layer)
        del self.comp_changes[:]
        self.model.undo_stack.undo()
        self.assertTrue(self.comp_changes)


if __name__ == '__main__':
    unittest.main()
