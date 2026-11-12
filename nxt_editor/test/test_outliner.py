"""The outliner, and turning the stage view on and off.

The outliner lists the graph's root nodes in the order they run, with each
node's children under it. It is opt in from the Window menu. The stage view
is on unless it is turned off in the Window menu, which is remembered.
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
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model, user_dir
from nxt_editor.dockwidgets.outliner import root_exec_order

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

# Saved out of order on purpose. The start point's chain runs first,
# /setup -> /build -> /publish, then the other chains in layer order:
# /loose, then /other -> /tidy.
GRAPH = {
    'version': '1.17', 'alias': 'outliner',
    'nodes': {
        '/loose': {},
        '/publish': {'execute_in': '/build'},
        '/tidy': {'execute_in': '/other'},
        '/build': {'execute_in': '/setup',
                   'child_order': ['rig', 'export']},
        '/build/export': {},
        '/build/rig': {'child_order': ['skeleton', 'controls']},
        '/build/rig/skeleton': {},
        '/build/rig/controls': {'enabled': False},
        '/other': {},
        '/setup': {'start_point': True},
    },
}
RUN_ORDER = ['/setup', '/build', '/publish', '/loose', '/other', '/tidy']


def write_graph(tmp):
    path = os.path.join(tmp, 'outliner.nxt')
    with open(path, 'w') as fp:
        json.dump(GRAPH, fp)
    return path


class RootOrder(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_outliner_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        stage = Session().load_file(filepath=write_graph(self.tmp))
        self.model = stage_model.StageModel(stage)

    def test_roots_follow_the_run_order(self):
        self.assertEqual(RUN_ORDER, root_exec_order(self.model))

    def test_a_branch_runs_each_follower_in_turn(self):
        self.model.set_node_exec_in('/loose', '/build')
        order = root_exec_order(self.model)
        # The follower first in the layer, the one nxt runs, comes first.
        self.assertEqual(['/setup', '/build', '/loose', '/publish',
                          '/other', '/tidy'], order)

    def test_a_loop_still_lists_every_root(self):
        self.model.set_node_exec_in('/other', '/tidy')
        order = root_exec_order(self.model)
        self.assertEqual(sorted(RUN_ORDER), sorted(order))
        self.assertEqual(RUN_ORDER[:3], order[:3])


class WindowCase(unittest.TestCase):

    def setUp(self):
        key = user_dir.USER_PREF.SHOW_STAGE_VIEW
        had = key in user_dir.user_prefs
        saved = user_dir.user_prefs.get(key)

        def restore():
            if had:
                user_dir.user_prefs[key] = saved
            elif key in user_dir.user_prefs:
                user_dir.user_prefs.pop(key)
        self.addCleanup(restore)
        if had:
            user_dir.user_prefs.pop(key)
        self.tmp = tempfile.mkdtemp(prefix='nxt_outliner_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = write_graph(self.tmp)
        self.win = self.open_window()

    def open_window(self):
        win = MainWindow(filepath=self.path)
        win.show()
        app.processEvents()
        self.addCleanup(self.close_window, win)
        return win

    @staticmethod
    def close_window(win):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            win.close()
            app.processEvents()
        win.deleteLater()
        app.processEvents()

    def window_action(self, action, checked):
        """Check or uncheck a Window menu item, as clicking it would."""
        menu = self.win.menuBar().window_menu
        menu.aboutToShow.emit()
        self.assertIn(action, menu.actions())
        action.setChecked(checked)
        menu.triggered.emit(action)
        app.processEvents()


class OutlinerTests(WindowCase):

    def setUp(self):
        super(OutlinerTests, self).setUp()
        self.outliner = self.win.outliner
        self.model = self.win.model
        self.tree = self.outliner.tree

    def show_outliner(self):
        self.window_action(self.win.app_actions.outliner_action, True)
        self.assertTrue(self.outliner.isVisible())

    def rows(self, parent=None):
        parent = parent or self.tree.invisibleRootItem()
        return [parent.child(i).text(0) for i in range(parent.childCount())]

    def test_it_is_off_in_the_default_layout(self):
        # Once shown, the saved layout remembers it like any other dock.
        self.win.reset_layout()
        self.assertFalse(self.outliner.isVisible())
        self.show_outliner()

    def test_roots_are_in_run_order_and_children_nest(self):
        self.show_outliner()
        self.assertEqual([p.lstrip('/') for p in RUN_ORDER], self.rows())
        build = self.outliner.items['/build']
        self.assertEqual(['rig', 'export'], self.rows(build))
        rig = self.outliner.items['/build/rig']
        self.assertEqual(['skeleton', 'controls'], self.rows(rig))
        self.assertTrue(rig.isExpanded())

    def test_start_points_have_an_icon(self):
        self.show_outliner()
        self.assertFalse(self.outliner.items['/setup'].icon(0).isNull())
        self.assertTrue(self.outliner.items['/build'].icon(0).isNull())

    def test_disabled_nodes_are_dimmed(self):
        self.show_outliner()
        item = self.outliner.items['/build/rig/controls']
        self.assertTrue(item.font(0).italic())
        self.assertFalse(self.outliner.items['/build/rig'].font(0).italic())

    def test_selecting_rows_selects_nodes(self):
        self.show_outliner()
        self.outliner.items['/build/rig'].setSelected(True)
        self.outliner.items['/tidy'].setSelected(True)
        self.assertEqual(['/build/rig', '/tidy'],
                         sorted(self.model.get_selected_nodes()))

    def test_selecting_nodes_selects_rows(self):
        self.show_outliner()
        self.model.set_selection(['/build/rig/skeleton'])
        selected = [i.data(0, 256) for i in self.tree.selectedItems()]
        self.assertEqual(['/build/rig/skeleton'], selected)

    def test_double_click_frames_the_node(self):
        self.show_outliner()
        framed = []
        self.model.frame_items.connect(framed.append)
        self.outliner.on_double_click(self.outliner.items['/publish'])
        self.assertEqual([('/publish',)], framed)
        self.assertEqual(['/publish'], self.model.get_selected_nodes())

    def test_it_follows_graph_edits(self):
        self.show_outliner()
        self.model.add_node(name='late', parent_path='/build/rig')
        app.processEvents()
        self.assertIn('/build/rig/late', self.outliner.items)
        self.model.delete_nodes(['/tidy'])
        app.processEvents()
        self.assertNotIn('tidy', self.rows())

    def test_closed_branches_stay_closed(self):
        self.show_outliner()
        self.outliner.items['/build'].setExpanded(False)
        self.model.add_node(name='late')
        app.processEvents()
        self.assertFalse(self.outliner.items['/build'].isExpanded())


class StageViewTests(WindowCase):

    def stage_view(self, win=None):
        return (win or self.win).open_files_tab_widget

    def test_it_is_on_by_default(self):
        self.assertTrue(self.stage_view().isVisible())

    def test_the_window_menu_turns_it_off_and_on(self):
        action = self.win.app_actions.stage_view_action
        self.window_action(action, False)
        self.assertFalse(self.stage_view().isVisible())
        self.window_action(action, True)
        self.assertTrue(self.stage_view().isVisible())

    def test_turning_it_off_is_remembered(self):
        self.window_action(self.win.app_actions.stage_view_action, False)
        key = user_dir.USER_PREF.SHOW_STAGE_VIEW
        self.assertIs(False, user_dir.user_prefs.get(key))
        second = self.open_window()
        self.assertFalse(self.stage_view(second).isVisible())
        menu = second.menuBar().window_menu
        menu.aboutToShow.emit()
        self.assertFalse(second.app_actions.stage_view_action.isChecked())


if __name__ == '__main__':
    unittest.main()
