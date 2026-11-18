"""A graph is framed around all of its nodes when it is opened, unless
Frame All on Open is turned off."""
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
from nxt_editor import stage_model, user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

KEY = user_dir.USER_PREF.FRAME_ON_OPEN
FAR = {
    'version': '1.17', 'alias': 'far',
    'nodes': {'/a': {}, '/b': {}},
    'meta_data': {'positions': {'/a': [3000.0, 2000.0],
                                '/b': [4600.0, 2900.0]}},
}
SMALL = {
    'version': '1.17', 'alias': 'small',
    'nodes': {'/a': {}},
    'meta_data': {'positions': {'/a': [600.0, 400.0]}},
}


class FrameOnOpen(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_frame_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        had = KEY in user_dir.user_prefs
        saved = user_dir.user_prefs.get(KEY)

        def restore():
            if had:
                user_dir.user_prefs[KEY] = saved
            elif KEY in user_dir.user_prefs:
                user_dir.user_prefs.pop(KEY)
        self.addCleanup(restore)
        self.wins = []
        self.hidden_docks = []

    def tearDown(self):
        # Shown again, so the layout the window saves is the one it had.
        for dock in self.hidden_docks:
            dock.show()
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            for win in self.wins:
                win.close()
                app.processEvents()
                win.deleteLater()
        app.processEvents()

    def open(self, graph):
        path = os.path.join(self.tmp, graph['alias'] + '.nxt')
        with open(path, 'w') as fp:
            json.dump(graph, fp)
        win = MainWindow(filepath=path)
        self.wins.append(win)
        win.show()
        app.processEvents()
        return win.view

    def center(self, view):
        return view.mapToScene(view.viewport().rect().center())

    def shown(self, view):
        return view.mapToScene(view.viewport().rect()).boundingRect()

    def test_it_is_on_with_no_preference(self):
        if KEY in user_dir.user_prefs:
            user_dir.user_prefs.pop(KEY)
        view = self.open(FAR)
        for path in ('/a', '/b'):
            rect = view.get_node_graphic(path).sceneBoundingRect()
            self.assertTrue(self.shown(view).contains(rect), path)

    def test_a_small_graph_is_not_zoomed_in(self):
        user_dir.user_prefs[KEY] = True
        view = self.open(SMALL)
        # A layout an earlier window saved can leave the graph too small
        # to fit even one node at 100%. Given room, as it is opened with.
        win = self.wins[-1]
        self.hidden_docks = [d for d in
                             win.findChildren(QtWidgets.QDockWidget)
                             if d.isVisible()]
        for dock in self.hidden_docks:
            dock.hide()
        win.resize(1400, 900)
        app.processEvents()
        view.frame_opened()
        self.assertEqual(1.0, view.scale_factor)
        rect = view.get_node_graphic('/a').sceneBoundingRect()
        center = self.center(view)
        # Within a pixel or two of the viewport's middle, as it is whole
        # pixels.
        self.assertAlmostEqual(rect.center().x(), center.x(), delta=4)
        self.assertAlmostEqual(rect.center().y(), center.y(), delta=4)

    def test_off_it_shows_the_origin(self):
        user_dir.user_prefs[KEY] = False
        view = self.open(FAR)
        center = self.center(view)
        self.assertAlmostEqual(0, center.x(), delta=2)
        self.assertAlmostEqual(0, center.y(), delta=2)
        self.assertEqual(1.0, view.scale_factor)

    def test_it_is_in_the_view_menu_after_frame_all(self):
        view = self.open(SMALL)
        win = self.wins[-1]
        actions = win.menu_bar.view_menu.actions()
        frame_all = actions.index(win.view_actions.frame_all_action)
        self.assertIs(win.view_actions.frame_on_open_action,
                      actions[frame_all + 1])
        action = win.view_actions.frame_on_open_action
        self.assertTrue(action.isCheckable())
        action.setChecked(True)
        action.trigger()
        self.assertFalse(user_dir.user_prefs[KEY])


if __name__ == '__main__':
    unittest.main()
