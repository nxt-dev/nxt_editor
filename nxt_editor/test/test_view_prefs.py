"""Small view and dialog conveniences.

The connection lines toggle is remembered like the grid is (#204), Animate
Nodes is in the View menu, Replace answers Ctrl+R as well as Ctrl+H, and
with no saved graph open, file dialogs start where a graph was last opened
from rather than wherever the editor was started (#70).
"""
# Builtin
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model, user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

TEST_DIR = os.path.dirname(os.path.abspath(__file__))


def restore(key, value):
    if value is None:
        try:
            user_dir.user_prefs.pop(key)
        except KeyError:
            pass
    else:
        user_dir.user_prefs[key] = value


class ViewPrefs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.win = MainWindow()
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def test_the_lines_toggle_is_remembered_for_new_tabs(self):
        key = user_dir.USER_PREF.SHOW_IMPLICIT
        saved = user_dir.user_prefs.get(key)
        try:
            action = self.win.view_actions.implicit_action
            action.setChecked(True)
            action.trigger()
            self.assertFalse(user_dir.user_prefs.get(key))
            os.chdir(TEST_DIR)
            stage = Session().load_file('StageInstanceTest.nxt')
            self.assertFalse(stage_model.StageModel(stage).implicit_connections)
        finally:
            restore(key, saved)

    def test_animate_nodes_is_in_the_view_menu(self):
        actions = self.win.menu_bar.view_menu.actions()
        self.assertIn(self.win.view_actions.animation_action, actions)

    def test_replace_answers_ctrl_r_as_well(self):
        shortcuts = [shortcut.toString() for shortcut in
                     self.win.code_editor_actions.replace_action.shortcuts()]
        self.assertIn('Ctrl+H', shortcuts)
        self.assertIn('Ctrl+R', shortcuts)


class LastOpenedFolder(unittest.TestCase):

    def setUp(self):
        self.saved = user_dir.editor_cache.get(user_dir.USER_PREF.RECENT_FILES)
        # Resolved, since nxt writes resolved paths and a temp folder
        # can have a short name on Windows.
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_last_opened_'))

    def tearDown(self):
        if self.saved is None:
            try:
                user_dir.editor_cache.pop(user_dir.USER_PREF.RECENT_FILES)
            except KeyError:
                pass
        else:
            user_dir.editor_cache[user_dir.USER_PREF.RECENT_FILES] = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dialogs_start_where_a_graph_was_last_opened(self):
        graph = os.path.join(self.tmp, 'last.nxt')
        user_dir.editor_cache[user_dir.USER_PREF.RECENT_FILES] = [graph]
        self.assertEqual(os.path.normcase(self.tmp),
                         os.path.normcase(user_dir.last_opened_dir()))

    def test_with_nothing_opened_yet_the_working_directory(self):
        user_dir.editor_cache[user_dir.USER_PREF.RECENT_FILES] = []
        self.assertEqual(os.getcwd(), user_dir.last_opened_dir())

    def test_a_folder_that_has_gone_is_not_offered(self):
        gone = os.path.join(self.tmp, 'gone', 'last.nxt')
        user_dir.editor_cache[user_dir.USER_PREF.RECENT_FILES] = [gone]
        self.assertEqual(os.getcwd(), user_dir.last_opened_dir())


if __name__ == '__main__':
    unittest.main()
