"""A look chosen in Preferences shows without a restart of the host.

Widgets take the look as they are made, so a change shows in the next
editor: each one puts the look the preferences ask for in place as it
opens, and Preferences offers to reopen the editor, with its graphs, in
the new look.
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
from Qt import QtGui, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# Internal
import nxt_editor  # noqa: E402
from nxt_editor import (colors, preference_editor, stage_model, theme,  # noqa: E402
                        user_dir)
from nxt_editor.main_window import MainWindow  # noqa: E402
from nxt_editor.mini_map import MiniMap  # noqa: E402
from nxt_editor.node_graphics_item import NodeGraphicsItem  # noqa: E402

PREF = user_dir.USER_PREF


class LookChange(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_look_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.prefs = user_dir.JsonPref(
            os.path.join(self.folder, 'prefs.json'))
        for name in ('user_prefs', 'hotkeys'):
            patch = mock.patch.object(user_dir, name, user_dir.JsonPref(
                os.path.join(self.folder, name + '.json')))
            patch.start()
            self.addCleanup(patch.stop)
        self.prefs = user_dir.user_prefs
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(theme.LOOK_ENV_VAR, None)
        os.environ.pop(theme.STYLESHEET_ENV_VAR, None)
        # Back to modern for the tests after these.
        self.addCleanup(theme.take_stored_look)
        self.addCleanup(self.prefs.__setitem__, PREF.LOOK, theme.LOOK_MODERN)

    def choose(self, look):
        self.prefs[PREF.LOOK] = look
        return theme.take_stored_look()


class TakenAsAnEditorOpens(LookChange):

    def test_a_new_look_is_put_in_place(self):
        self.choose(theme.LOOK_MODERN)
        self.assertTrue(self.choose(theme.LOOK_CLASSIC))
        self.assertEqual(theme.LOOK_CLASSIC, theme.LOOK)
        self.assertEqual(theme.CLASSIC['BASE'], theme.BASE)
        self.assertEqual(1, theme.NODE_MONO)

    def test_back_to_modern_leaves_nothing_of_the_last_look(self):
        self.choose(theme.LOOK_MODERN)
        modern = dict(theme.tokens())
        self.choose(theme.LOOK_CLASSIC)
        self.choose(theme.LOOK_MODERN)
        self.assertEqual(modern, dict(theme.tokens()))

    def test_the_same_look_again_changes_nothing(self):
        self.choose(theme.LOOK_CLASSIC)
        self.assertFalse(self.choose(theme.LOOK_CLASSIC))

    def test_values_kept_from_the_look_follow_it(self):
        self.choose(theme.LOOK_CLASSIC)
        self.assertEqual(QtGui.QColor(theme.CLASSIC['GRAPH']),
                         colors.GRAPH_BG_COLOR)
        self.assertEqual(QtGui.QColor(theme.CLASSIC['SELECTED']),
                         colors.SELECTED)
        self.assertEqual(theme.CLASSIC['NODE_RADIUS'],
                         NodeGraphicsItem.ROUND_X)
        self.assertEqual(theme.color(theme.CLASSIC['BASE'], 0.92),
                         MiniMap.BG_COLOR)
        self.choose(theme.LOOK_MODERN)
        self.assertEqual(QtGui.QColor(theme.GRAPH), colors.GRAPH_BG_COLOR)
        self.assertEqual(theme.NODE_RADIUS, NodeGraphicsItem.ROUND_X)

    def test_host_on_its_own_is_modern(self):
        self.choose(theme.LOOK_CLASSIC)
        with mock.patch.object(theme, 'running_host', return_value=''),                 mock.patch.object(theme, 'host_colors', return_value={}):
            self.choose(theme.LOOK_HOST)
        self.assertEqual(theme.LOOK_MODERN, theme.LOOK)


class Reopen(LookChange):

    def setUp(self):
        super(Reopen, self).setUp()
        self.choose(theme.LOOK_MODERN)
        self.graph = os.path.join(self.folder, 'graph.nxt')
        with open(self.graph, 'w') as handle:
            json.dump({'version': '1.17', 'alias': 'graph',
                       'nodes': {'/node': {}}}, handle)
        self.win = MainWindow(filepath=self.graph)
        self.windows = [self.win]

    def tearDown(self):
        for window in self.windows:
            if window.preference_editor is not None:
                window.preference_editor.deleteLater()
                window.preference_editor = None
            with mock.patch.object(stage_model.StageModel,
                                   'get_unsaved_changes', return_value=[]):
                window.close()
                app.processEvents()
            window.deleteLater()
        app.processEvents()

    def test_choosing_a_look_offers_to_reopen(self):
        dialog = self.win.open_preferences()
        with mock.patch.object(dialog, 'offer_reopen') as offer:
            dialog.editors[PREF.LOOK].setCurrentIndex(
                dialog.editors[PREF.LOOK].findData(theme.LOOK_CLASSIC))
            app.processEvents()
        offer.assert_called_once()
        self.assertEqual(theme.LOOK_CLASSIC, self.prefs[PREF.LOOK])

    def test_reopen_now_opens_the_same_graphs_in_the_new_look(self):
        dialog = self.win.open_preferences()
        self.prefs[PREF.LOOK] = theme.LOOK_CLASSIC
        with mock.patch.object(QtWidgets.QMessageBox, 'exec_'), \
                mock.patch.object(QtWidgets.QMessageBox, 'clickedButton',
                                  lambda box: box.defaultButton()):
            new = dialog.offer_reopen()
        self.assertIsNotNone(new)
        self.windows.append(new)
        self.assertIsNot(new, self.win)
        self.assertFalse(self.win.isVisible())
        self.assertEqual(theme.LOOK_CLASSIC, theme.LOOK)
        self.assertEqual([self.graph.replace(os.sep, '/')],
                         [path.replace(os.sep, '/')
                          for path in new.open_paths()])

    def test_later_leaves_the_editor_open(self):
        dialog = self.win.open_preferences()
        with mock.patch.object(QtWidgets.QMessageBox, 'exec_'),                 mock.patch.object(MainWindow, 'reopen') as reopen:
            self.assertIsNone(dialog.offer_reopen())
        reopen.assert_not_called()

    def test_a_cancelled_close_keeps_the_editor(self):
        with mock.patch.object(MainWindow, 'close', return_value=False):
            self.assertIsNone(self.win.reopen())
        self.assertTrue(app.quitOnLastWindowClosed())

    def test_the_host_opens_the_new_editor_when_it_says_how(self):
        opened = []
        with mock.patch.object(nxt_editor, 'host_opener',
                               lambda paths: opened.append(paths) or 'new'), \
                mock.patch.object(stage_model.StageModel,
                                  'get_unsaved_changes', return_value=[]):
            self.assertEqual('new', self.win.reopen())
        self.assertEqual(1, len(opened))
        self.assertEqual(1, len(opened[0]))


if __name__ == '__main__':
    unittest.main()
