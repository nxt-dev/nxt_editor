"""The outliner, and turning the stage view on and off.

The outliner lists the graph's root nodes in the order they run, grouped by
the start point whose build runs them, with each node's children under it.
Rows show the colors of the layers a node is on, and a search box finds
nodes at any depth by a regex on their name. It is opt in from the Window
menu. The stage view is on unless it is turned off in the Window menu,
which is remembered.
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
from Qt import QtCore, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model, user_dir
from nxt_editor.dockwidgets import outliner as outliner_module
from nxt_editor.dockwidgets.outliner import (build_sections, root_exec_order,
                                             search_pattern)

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
IN_THE_BUILD = ['/setup', '/build', '/publish']
NOT_IN_THE_BUILD = ['/loose', '/other', '/tidy']


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

    def test_roots_are_grouped_by_the_build_that_runs_them(self):
        self.assertEqual([('/setup', IN_THE_BUILD), (None, NOT_IN_THE_BUILD)],
                         build_sections(self.model))

    def test_each_start_point_has_its_own_build(self):
        self.model.set_startpoints(['/other'], state=True)
        self.assertEqual([('/other', ['/other', '/tidy']),
                          ('/setup', IN_THE_BUILD), (None, ['/loose'])],
                         sorted(build_sections(self.model),
                                key=lambda s: (s[0] is None, s[0] or '')))

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

    def section_rows(self, start=None):
        return self.rows(self.outliner.sections[start or ''])

    def search(self, text):
        self.outliner.search.setText(text)
        app.processEvents()

    def test_it_is_off_in_the_default_layout(self):
        # Once shown, the saved layout remembers it like any other dock.
        self.win.reset_layout()
        self.assertFalse(self.outliner.isVisible())
        self.show_outliner()

    def test_roots_are_in_run_order_and_children_nest(self):
        self.show_outliner()
        self.assertEqual(['Build from setup', outliner_module.NOT_IN_A_BUILD],
                         self.rows())
        self.assertEqual([p.lstrip('/') for p in IN_THE_BUILD],
                         self.section_rows('/setup'))
        self.assertEqual([p.lstrip('/') for p in NOT_IN_THE_BUILD],
                         self.section_rows())
        build = self.outliner.items['/build']
        self.assertEqual(['rig', 'export'], self.rows(build))
        rig = self.outliner.items['/build/rig']
        self.assertEqual(['skeleton', 'controls'], self.rows(rig))
        self.assertTrue(rig.isExpanded())

    def test_section_headings_cannot_be_selected(self):
        self.show_outliner()
        heading = self.outliner.sections['/setup']
        self.assertFalse(heading.flags() & QtCore.Qt.ItemIsSelectable)

    def test_rows_carry_the_colors_of_the_nodes_layers(self):
        self.show_outliner()
        item = self.outliner.items['/build']
        color = self.model.get_layer_color(self.model.top_layer)
        self.assertEqual([color], item.data(0, outliner_module.LAYERS_ROLE))

    def test_a_search_finds_a_node_deep_in_the_hierarchy(self):
        self.show_outliner()
        self.search('skel')
        # The match, and the nodes above it so you can see where it is.
        self.assertEqual(['/build', '/build/rig', '/build/rig/skeleton'],
                         sorted(self.outliner.items))
        self.assertEqual(['/build/rig/skeleton'], self.outliner.matches)
        self.assertTrue(self.outliner.items['/build/rig'].isExpanded())
        # Only the section it is in is shown.
        self.assertEqual(['Build from setup'], self.rows())

    def test_a_search_is_a_regex_and_ignores_case(self):
        self.show_outliner()
        self.search('^(TIDY|loose)$')
        self.assertEqual(['/loose', '/tidy'], sorted(self.outliner.matches))

    def test_a_search_that_is_not_a_regex_yet_is_taken_as_text(self):
        self.assertTrue(search_pattern('rig[').search('my_rig[0]'))
        self.assertIsNone(search_pattern('   '))

    def test_clearing_the_search_shows_everything_again(self):
        self.show_outliner()
        self.search('skel')
        self.search('')
        self.assertEqual(sorted(GRAPH['nodes']), sorted(self.outliner.items))

    def test_enter_frames_the_first_match(self):
        self.show_outliner()
        framed = []
        self.model.frame_items.connect(framed.append)
        self.search('export')
        self.outliner.search.returnPressed.emit()
        self.assertEqual([('/build/export',)], framed)

    def menu_for(self, path):
        item = self.outliner.items[path]
        self.tree.scrollToItem(item)
        pos = self.tree.visualItemRect(item).center()
        return self.outliner.context_menu(pos)

    def test_right_click_shows_the_graphs_node_menu(self):
        self.show_outliner()
        menu = self.menu_for('/build/rig')
        texts = [a.text() for a in menu.actions()]
        self.assertEqual('Frame in Graph', texts[0])
        self.assertIn('Execute /build/rig', texts)
        for action in (self.win.execute_actions.execute_selected_action,
                       self.win.node_actions.disable_node_action,
                       self.win.node_actions.delete_node_action,
                       self.win.execute_actions.toggle_start_action):
            self.assertIn(action, menu.actions())
        menu.deleteLater()

    def test_right_click_selects_the_row_it_was_on(self):
        self.show_outliner()
        self.model.set_selection(['/tidy'])
        menu = self.menu_for('/build/export')
        self.assertEqual(['/build/export'], self.model.get_selected_nodes())
        menu.deleteLater()
        # One already in the selection keeps the rest of it.
        self.model.set_selection(['/tidy', '/loose'])
        menu = self.menu_for('/loose')
        self.assertEqual(['/loose', '/tidy'],
                         sorted(self.model.get_selected_nodes()))
        menu.deleteLater()

    def test_the_menu_disables_the_row(self):
        self.show_outliner()
        menu = self.menu_for('/build/export')
        self.win.node_actions.disable_node_action.trigger()
        app.processEvents()
        self.assertFalse(self.model.get_node_enabled('/build/export'))
        menu.deleteLater()

    def test_right_click_on_a_heading_shows_nothing(self):
        self.show_outliner()
        heading = self.outliner.sections['/setup']
        pos = self.tree.visualItemRect(heading).center()
        self.assertIsNone(self.outliner.context_menu(pos))

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
