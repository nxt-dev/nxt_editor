"""Leaving the code editor without changing the code is not an edit.

Accepting compares the text in the editor with the node's code, and when
they are the same it only leaves edit mode. The comparison was made
against the text of a bytes literal, which never matches anything, so
every accept set the code again: an undo entry that undoes nothing, a
layer with unsaved changes nobody made, and, for a node whose code comes
from an instance or another layer, a copy of that code written onto the
target layer.

Accepting is also what happens when another node is selected or the graph
is executed while the editor is open, so clicking into the code and then
away was enough.
"""
# Builtin
import os
import sys
import unittest
from unittest import mock

# External
from Qt import QtCore, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt import DATA_STATE  # noqa: E402

# Imported after the application exists, because building the main window
# touches widgets.
from nxt_editor import stage_model  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402

PLAIN = '/inst_source1'
TOKEN = '/inst_source4/inst_source4_child'
INHERITED = '/inst_target4/inst_source4_child'
TOKEN_CODE = '"The base should be 1 is it? base == ${base}"'
ACCENTED = ['# café', 'name = "señor"', '']
ACCENTED_TEXT = '\n'.join(ACCENTED)


class UnchangedExit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.win = MainWindow(filepath="StageInstanceTest.nxt")
        cls.win.resize(1400, 900)
        cls.win.show()
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.model = cls.ce.stage_model
        cls.model.set_selection([PLAIN])
        cls.win.resizeDocks([cls.ce], [420], QtCore.Qt.Vertical)
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        # A test that fails can leave the layer changed, and closing would
        # then stop to ask about saving it, with nobody there to answer.
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            cls.win.close()
        cls.win = None

    def setUp(self):
        self.ce.exit_editing()
        self.start_count = self.model.undo_stack.index()
        self.addCleanup(self.put_back)

    def put_back(self):
        """Leave the graph, and the undo stack, the way the test found it."""
        self.ce.exit_editing()
        stack = self.model.undo_stack
        while stack.index() > self.start_count:
            stack.undo()

    def edit(self, node_path):
        self.model.set_selection([node_path])
        app.processEvents()
        self.assertEqual(node_path, self.ce.node_path)
        self.ce.enter_editing()
        self.assertTrue(self.ce.editing_active)

    def code_edits(self):
        """How many times the code was set since the test started.

        Selecting a node goes on the undo stack as well, so the commands
        are told apart by what they say they did.
        """
        stack = self.model.undo_stack
        return len([i for i in range(self.start_count, stack.index())
                    if stack.text(i).startswith('Changed compute')])

    def local_code(self, node_path):
        return self.model.node_has_code(node_path, self.model.target_layer)

    def test_accepting_untouched_code_is_not_an_undo_step(self):
        self.edit(PLAIN)
        self.ce.accept_edit()
        self.assertFalse(self.ce.editing_active)
        self.assertEqual(0, self.code_edits(),
                         'accepting code nobody touched went on the undo '
                         'stack')

    def test_accepting_untouched_code_leaves_the_layer_saved(self):
        self.assertEqual([], self.model.get_unsaved_changes())
        self.edit(PLAIN)
        self.ce.accept_edit()
        self.assertEqual([], self.model.get_unsaved_changes(),
                         'accepting code nobody touched left the layer '
                         'with unsaved changes')

    def test_untouched_code_with_a_token(self):
        self.assertEqual([], self.model.get_unsaved_changes())
        self.edit(TOKEN)
        self.assertEqual(TOKEN_CODE, self.editor.toPlainText(),
                         'editing shows the code as written, token and all')
        self.ce.accept_edit()
        self.assertEqual(0, self.code_edits())
        self.assertEqual([], self.model.get_unsaved_changes())
        self.assertEqual(TOKEN_CODE,
                         self.model.get_node_code_string(TOKEN))

    def test_untouched_code_with_accented_characters(self):
        self.model.set_node_code_lines(PLAIN, ACCENTED)
        self.assertEqual(1, self.code_edits())
        self.edit(PLAIN)
        self.assertEqual(ACCENTED_TEXT, self.editor.toPlainText())
        self.ce.accept_edit()
        self.assertEqual(1, self.code_edits(),
                         'accepting untouched code with accented characters '
                         'went on the undo stack')
        self.assertEqual(ACCENTED_TEXT,
                         self.model.get_node_code_string(PLAIN))

    def test_untouched_inherited_code_is_not_copied_to_the_layer(self):
        self.assertFalse(self.local_code(INHERITED))
        self.edit(INHERITED)
        self.assertEqual(TOKEN_CODE, self.editor.toPlainText())
        self.ce.accept_edit()
        self.assertEqual(0, self.code_edits())
        self.assertFalse(self.local_code(INHERITED),
                         'the code the node gets from its instance was '
                         'written onto the node itself')

    def test_selecting_another_node_while_editing_is_not_an_edit(self):
        self.edit(PLAIN)
        self.model.set_selection([TOKEN])
        app.processEvents()
        self.assertFalse(self.ce.editing_active)
        self.assertEqual(0, self.code_edits())
        self.assertEqual([], self.model.get_unsaved_changes())

    def test_changed_code_is_one_undo_step(self):
        self.edit(PLAIN)
        self.editor.setPlainText('# Inst Source\nchanged = True')
        self.ce.accept_edit()
        self.assertFalse(self.ce.editing_active)
        self.assertEqual(1, self.code_edits())
        self.assertEqual('# Inst Source\nchanged = True',
                         self.model.get_node_code_string(PLAIN))
        self.assertEqual([self.model.target_layer],
                         self.model.get_unsaved_changes())
        self.model.undo_stack.undo()
        self.assertEqual('# Inst Source',
                         self.model.get_node_code_string(PLAIN))

    def test_writing_out_what_a_token_resolves_to_is_an_edit(self):
        resolved = self.model.get_node_code_string(TOKEN,
                                                   DATA_STATE.RESOLVED)
        self.assertNotEqual(TOKEN_CODE, resolved)
        self.edit(TOKEN)
        self.editor.setPlainText(resolved)
        self.ce.accept_edit()
        self.assertEqual(1, self.code_edits())
        self.assertEqual(resolved, self.model.get_node_code_string(TOKEN))


if __name__ == '__main__':
    unittest.main()
