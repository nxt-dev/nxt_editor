"""The main window's actions must come back after typing in the code editor.

The code editor disables every main window action while it has focus, so
typing cannot fire them. It recorded their enabled states to put back
afterwards. Suspending twice recorded the already disabled states as the
real ones, and restoring then left the whole main window greyed out. Save
Layer was the one people noticed: the layer really was modified, closing
still offered to save it, but the menu entry could not be clicked.

A second suspend is a normal thing to happen: the find and go to line
fields suspend on their own focus, on top of the editor having done so.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class GlobalActionsComeBack(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.win = MainWindow(filepath="StageInstanceTest.nxt")
        cls.editor = cls.win.code_editor.editor
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def setUp(self):
        self.editor.restore_global_actions()
        self.save_action = self.win.layer_actions.save_layer_action
        self.save_action.setEnabled(True)

    def enabled(self):
        return [a.isEnabled() for a in self.win.get_global_actions()]

    def test_suspend_then_restore(self):
        before = self.enabled()
        self.editor.suspend_global_actions()
        self.assertFalse(any(self.enabled()), 'nothing should be live')
        self.editor.restore_global_actions()
        self.assertEqual(before, self.enabled())

    def test_suspending_twice_still_restores(self):
        # The editor takes focus, then a find field does. Both suspend.
        before = self.enabled()
        self.editor.suspend_global_actions()
        self.editor.suspend_global_actions()
        self.editor.restore_global_actions()
        self.assertEqual(before, self.enabled(),
                         'a second suspend recorded the disabled states and '
                         'restoring made them permanent')

    def test_save_layer_survives_it(self):
        self.editor.suspend_global_actions()
        self.editor.suspend_global_actions()
        self.editor.restore_global_actions()
        self.assertTrue(self.save_action.isEnabled(),
                        'Save Layer stayed greyed out')

    def test_hiding_the_editor_restores(self):
        # Selecting a node with no code hides it, and it never gets a
        # focus out to put things back.
        before = self.enabled()
        self.editor.suspend_global_actions()
        self.editor.hide()
        app.processEvents()
        self.assertEqual(before, self.enabled(),
                         'hiding the editor stranded the actions disabled')
        self.editor.show()

    def test_restore_without_suspend_is_harmless(self):
        before = self.enabled()
        self.editor.restore_global_actions()
        self.assertEqual(before, self.enabled())


if __name__ == '__main__':
    unittest.main()
