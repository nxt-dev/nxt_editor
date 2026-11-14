"""The outliner, and turning the stage view on and off.

The outliner lists the graph's root nodes in the order they run, grouped by
the start point whose build runs them, with each node's children under it.
Rows show the colors of the layers a node is on, and a search box finds
nodes at any depth by name, with * for anything and commas between names. It is opt in from the Window
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
from Qt import QtCore, QtTest, QtWidgets

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
        """Type text and stop, as the search waits for."""
        self.outliner.search.setText(text)
        self.wait_for_search()

    def wait_for_search(self):
        """Until the search has run and the tree is rebuilt."""
        outliner = self.outliner
        for _ in range(100):
            QtTest.QTest.qWait(outliner_module.SEARCH_DELAY_MS // 3)
            if not (outliner.search_timer.isActive() or
                    outliner.rebuild_timer.isActive()):
                break
        app.processEvents()

    def test_typing_does_not_search_on_every_key(self):
        self.show_outliner()
        with mock.patch.object(self.outliner, 'rebuild') as rebuild:
            QtTest.QTest.keyClicks(self.outliner.search, 'skel')
            app.processEvents()
            rebuild.assert_not_called()
            self.wait_for_search()
        self.assertEqual(1, rebuild.call_count)

    def test_enter_searches_straight_away(self):
        self.show_outliner()
        framed = []
        self.model.frame_items.connect(framed.append)
        self.outliner.search.setText('export')
        self.outliner.search.returnPressed.emit()
        self.assertEqual(['/build/export'], self.outliner.matches)
        self.assertEqual([('/build/export',)], framed)

    def test_clearing_shows_everything_straight_away(self):
        self.show_outliner()
        self.search('skel')
        self.outliner.search.setText('')
        app.processEvents()
        self.assertEqual(sorted(GRAPH['nodes']), sorted(self.outliner.items))

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

    def test_commas_find_several_names_and_case_is_ignored(self):
        self.show_outliner()
        self.search('TIDY, loose')
        self.assertEqual(['/loose', '/tidy'], sorted(self.outliner.matches))

    def test_a_star_stands_for_anything(self):
        self.show_outliner()
        self.search('s*on')
        self.assertEqual(['/build/rig/skeleton'], self.outliner.matches)

    def test_nothing_typed_searches_for_nothing(self):
        self.assertIsNone(search_pattern('   '))
        self.assertIsNone(search_pattern(' , * '))

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

    def empty_space_menu(self):
        self.tree.collapseAll()
        app.processEvents()
        viewport = self.tree.viewport().rect()
        pos = QtCore.QPoint(viewport.center().x(), viewport.bottom() - 2)
        self.assertIsNone(self.tree.itemAt(pos))
        return self.outliner.context_menu(pos)

    def test_right_click_off_the_rows_adds_or_pastes_a_node(self):
        self.show_outliner()
        self.model.set_selection(['/tidy'])
        menu = self.empty_space_menu()
        # As in empty space in the graph: nothing picked, so a new or
        # pasted node goes at the top of the hierarchy.
        self.assertEqual([], self.model.get_selected_nodes())
        for action in (self.win.node_actions.add_node_action,
                       self.win.node_actions.paste_node_action):
            self.assertIn(action, menu.actions())
        menu.deleteLater()

    def test_a_node_added_from_there_lands_in_view(self):
        self.show_outliner()
        menu = self.empty_space_menu()
        before = set(self.model.comp_layer.descendants())
        self.win.node_actions.add_node_action.trigger()
        app.processEvents()
        added = set(self.model.comp_layer.descendants()) - before
        self.assertEqual(1, len(added))
        path = added.pop()
        self.assertEqual(1, path.count('/'))
        view = self.win.view
        x, y = self.model.get_node_pos(path)
        shown = view.mapToScene(view.viewport().rect()).boundingRect()
        self.assertTrue(shown.contains(QtCore.QPointF(x, y)), (x, y))
        menu.deleteLater()

    def test_start_points_are_marked(self):
        self.show_outliner()
        points = outliner_module.POINTS_ROLE
        self.assertEqual([outliner_module.START],
                         self.outliner.items['/setup'].data(0, points))
        self.assertIsNone(self.outliner.items['/build'].data(0, points))
        self.assertIn('Start point',
                      self.outliner.items['/setup'].toolTip(0))

    def test_break_and_skip_points_show_on_their_rows(self):
        self.show_outliner()
        self.model.set_breakpoints(['/build/export'], True)
        self.model.toggle_skippoints(['/build/export', '/tidy'])
        self.addCleanup(self.model.clear_breakpoints)
        self.addCleanup(self.model.set_skippoints, ['/build/export', '/tidy'],
                        False)
        app.processEvents()
        points = outliner_module.POINTS_ROLE
        # In the graph's order: start, skip, break.
        self.assertEqual([outliner_module.SKIP, outliner_module.BREAK],
                         self.outliner.items['/build/export'].data(0, points))
        self.assertIn('Skip point, Breakpoint',
                      self.outliner.items['/build/export'].toolTip(0))
        self.assertEqual([outliner_module.SKIP],
                         self.outliner.items['/tidy'].data(0, points))
        self.assertIsNone(self.outliner.items['/loose'].data(0, points))
        # Taken off again, the row follows.
        self.model.set_breakpoints(['/build/export'], False)
        app.processEvents()
        self.assertEqual([outliner_module.SKIP],
                         self.outliner.items['/build/export'].data(0, points))

    def test_a_point_changes_the_row_without_building_the_tree(self):
        self.show_outliner()
        row = self.outliner.items['/tidy']
        with mock.patch.object(self.outliner, 'rebuild') as rebuild:
            self.model.set_breakpoints(['/tidy'], True)
            self.model.toggle_skippoints(['/tidy'])
            app.processEvents()
        self.addCleanup(self.model.clear_breakpoints)
        self.addCleanup(self.model.set_skippoints, ['/tidy'], False)
        rebuild.assert_not_called()
        self.assertIs(row, self.outliner.items['/tidy'])
        self.assertEqual([outliner_module.SKIP, outliner_module.BREAK],
                         row.data(0, outliner_module.POINTS_ROLE))

    def test_an_edit_that_changes_the_tree_builds_it_again(self):
        self.show_outliner()
        self.model.add_node(name='extra', parent_path='/build/export')
        app.processEvents()
        self.assertIn('/build/export/extra', self.outliner.items)
        self.model.set_node_exec_in('/loose', '/publish')
        app.processEvents()
        self.assertIn('loose', self.section_rows('/setup'))

    def paint_row(self, state):
        """A row painted in state, as an image."""
        from Qt import QtGui
        delegate = outliner_module.NodeRowDelegate()
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem('row')
        item.setData(['#99cc33'], outliner_module.LAYERS_ROLE)
        model.appendRow(item)
        image = QtGui.QImage(200, 30, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtGui.QColor('#242424'))
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 200, 30)
        option.state = state | QtWidgets.QStyle.State_Enabled
        painter = QtGui.QPainter(image)
        delegate.paint(painter, option, model.index(0, 0))
        painter.end()
        return image

    def test_hover_and_selection_only_outline_the_row(self):
        from Qt import QtGui
        style = QtWidgets.QStyle
        plain = self.paint_row(style.State_None)
        hovered = self.paint_row(style.State_MouseOver)
        selected = self.paint_row(style.State_Selected)
        inside = QtCore.QPoint(150, 15)
        edge = QtCore.QPoint(100, 1)
        for image in (plain, hovered, selected):
            self.assertEqual('#99cc33',
                             QtGui.QColor(image.pixel(inside)).name())
        # Hovered and selected edges differ from each other and the plain.
        edges = {QtGui.QColor(image.pixel(edge)).name()
                 for image in (plain, hovered, selected)}
        self.assertEqual(3, len(edges))

    def test_nothing_fills_the_space_beside_a_selected_row(self):
        from Qt import QtGui
        from nxt_editor import theme
        # Fusion, as on Linux and in some hosts, filled the space beside a
        # selected row; the Windows style does not.
        before = app.style().objectName()
        app.setStyle('Fusion')
        self.addCleanup(app.setStyle, before)
        self.show_outliner()
        self.outliner.setFloating(True)
        self.outliner.resize(360, 560)
        self.model.set_selection(['/build/rig'])
        for _ in range(10):
            app.processEvents()
        item = self.outliner.items['/build/rig']
        rect = self.tree.visualItemRect(item)
        image = self.tree.viewport().grab().toImage()
        # Nothing but the background, and the arrow, left of the row.
        greys = {QtGui.QColor(image.pixel(x, rect.top() + 2)).name()
                 for x in range(0, rect.left())}
        self.assertEqual({theme.BASE}, greys)

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

    def double_click(self, path, modifiers=QtCore.Qt.NoModifier):
        held = mock.patch.object(QtWidgets.QApplication, 'keyboardModifiers',
                                 return_value=modifiers)
        with held:
            self.outliner.on_double_click(self.outliner.items[path])
        app.processEvents()

    def test_double_click_collapses_the_node_as_in_the_graph(self):
        self.show_outliner()
        self.assertFalse(self.model.get_node_collapse('/build'))
        self.double_click('/build')
        self.assertTrue(self.model.get_node_collapse('/build'))
        self.assertFalse(self.outliner.items['/build'].isExpanded())
        self.double_click('/build')
        self.assertFalse(self.model.get_node_collapse('/build'))
        self.assertTrue(self.outliner.items['/build'].isExpanded())

    def test_shift_double_click_does_everything_below_as_one(self):
        self.show_outliner()
        # A mixed hierarchy: only rig is collapsed.
        self.model.set_node_collapse(['/build/rig'], value=True)
        self.double_click('/build', QtCore.Qt.ShiftModifier)
        below = ['/build', '/build/rig', '/build/rig/skeleton',
                 '/build/export']
        self.assertTrue(all(self.model.get_node_collapse(p) for p in below))
        self.double_click('/build', QtCore.Qt.ShiftModifier)
        self.assertFalse(any(self.model.get_node_collapse(p) for p in below))
        self.assertTrue(self.outliner.items['/build/rig'].isExpanded())

    def click_arrow(self, path, modifiers=QtCore.Qt.NoModifier):
        item = self.outliner.items[path]
        self.tree.scrollToItem(item)
        rect = self.tree.visualItemRect(item)
        pos = QtCore.QPoint(rect.left() - self.tree.indentation() // 2,
                            rect.center().y())
        self.assertIs(item, self.tree.arrow_at(pos))
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton,
                                modifiers, pos)
        app.processEvents()

    def test_the_arrow_collapses_the_node_as_double_click_does(self):
        self.show_outliner()
        self.click_arrow('/build')
        self.assertTrue(self.model.get_node_collapse('/build'))
        self.assertFalse(self.model.get_node_collapse('/build/rig'))
        self.assertFalse(self.outliner.items['/build'].isExpanded())
        self.click_arrow('/build')
        self.assertFalse(self.model.get_node_collapse('/build'))
        self.assertTrue(self.outliner.items['/build'].isExpanded())

    def test_shift_on_the_arrow_does_everything_below(self):
        self.show_outliner()
        self.model.set_node_collapse(['/build/rig'], value=True)
        self.click_arrow('/build', QtCore.Qt.ShiftModifier)
        below = ['/build', '/build/rig', '/build/rig/skeleton',
                 '/build/export']
        self.assertTrue(all(self.model.get_node_collapse(p) for p in below))
        self.click_arrow('/build', QtCore.Qt.ShiftModifier)
        self.assertFalse(any(self.model.get_node_collapse(p) for p in below))
        self.assertTrue(self.outliner.items['/build/rig'].isExpanded())

    def test_shift_on_a_groups_arrow_does_every_node_in_it(self):
        self.show_outliner()
        heading = self.outliner.sections['/setup']
        self.tree.scrollToItem(heading)
        rect = self.tree.visualItemRect(heading)
        pos = QtCore.QPoint(rect.left() - self.tree.indentation() // 2,
                            rect.center().y())
        self.assertIs(heading, self.tree.arrow_at(pos))
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton,
                                QtCore.Qt.ShiftModifier, pos)
        app.processEvents()
        in_it = ['/build', '/build/rig']
        self.assertTrue(all(self.model.get_node_collapse(p) for p in in_it))
        # The group stays open to show its collapsed nodes.
        self.assertTrue(self.outliner.sections['/setup'].isExpanded())
        self.assert_rows_match_the_graph()
        # All collapsed: again expands them all, as one undo.
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton,
                                QtCore.Qt.ShiftModifier, pos)
        app.processEvents()
        self.assertFalse(any(self.model.get_node_collapse(p) for p in in_it))
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertTrue(all(self.model.get_node_collapse(p) for p in in_it))

    def test_shift_double_click_on_a_group_does_the_same(self):
        self.show_outliner()
        heading = self.outliner.sections['/setup']
        held = mock.patch.object(QtWidgets.QApplication, 'keyboardModifiers',
                                 return_value=QtCore.Qt.ShiftModifier)
        with held:
            self.outliner.on_double_click(heading)
        app.processEvents()
        self.assertTrue(self.model.get_node_collapse('/build'))

    def test_a_plain_click_on_a_groups_arrow_only_closes_the_group(self):
        self.show_outliner()
        heading = self.outliner.sections['/setup']
        rect = self.tree.visualItemRect(heading)
        pos = QtCore.QPoint(rect.left() - self.tree.indentation() // 2,
                            rect.center().y())
        QtTest.QTest.mouseClick(self.tree.viewport(), QtCore.Qt.LeftButton,
                                QtCore.Qt.NoModifier, pos)
        app.processEvents()
        self.assertFalse(heading.isExpanded())
        self.assertFalse(self.model.get_node_collapse('/build'))

    def test_rows_follow_a_node_collapsed_from_the_graph(self):
        self.show_outliner()
        self.model.set_selection(['/build'])
        self.win.node_actions.toggle_collapse_action.trigger()
        app.processEvents()
        self.assertFalse(self.outliner.items['/build'].isExpanded())

    def test_ctrl_double_click_renames_in_the_row(self):
        self.show_outliner()
        opened = []

        def answer(dialog):
            opened.append(dialog.geometry())
            dialog.line_edit.setText('assemble')
            dialog.accept()
            return 1
        with mock.patch.object(outliner_module.NameEditDialog, 'exec_',
                               answer):
            self.double_click('/publish', QtCore.Qt.ControlModifier)
        self.assertTrue(self.model.node_exists('/assemble'))
        row = self.outliner.items['/assemble']
        rect = self.tree.visualItemRect(row)
        top_left = self.tree.viewport().mapToGlobal(rect.topLeft())
        self.assertEqual(top_left.y(), opened[0].y())

    def test_the_graphs_hotkeys_work_in_the_tree(self):
        self.show_outliner()
        actions = self.tree.actions()
        for action in (self.win.node_actions.disable_node_action,
                       self.win.node_actions.add_node_action,
                       self.win.node_actions.delete_node_action,
                       self.win.node_actions.rename_node_action,
                       self.win.execute_actions.toggle_start_action,
                       self.win.view_actions.frame_selection_action):
            self.assertIn(action, actions)
        # Not the graph's arrow keys, which move between rows here.
        self.assertNotIn(self.win.view_actions.pick_walk_down_action,
                         actions)

    def test_letters_do_not_jump_to_rows(self):
        self.show_outliner()
        self.tree.setCurrentItem(self.outliner.items['/setup'])
        self.tree.keyboardSearch('t')
        self.assertIs(self.outliner.items['/setup'],
                      self.tree.currentItem())

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

    def assert_rows_match_the_graph(self):
        for path, item in self.outliner.items.items():
            if item.childCount():
                self.assertEqual(not self.model.get_node_collapse(path),
                                 item.isExpanded(), path)

    def test_closing_a_row_with_the_keyboard_collapses_its_node(self):
        self.show_outliner()
        self.outliner.items['/build'].setExpanded(False)
        app.processEvents()
        self.assertTrue(self.model.get_node_collapse('/build'))
        self.assert_rows_match_the_graph()

    def test_selecting_inside_a_collapsed_node_keeps_it_collapsed(self):
        # Selecting used to open the rows above the selected one, the
        # graph's node stayed collapsed, and the next click on the arrow
        # expanded it rather than collapsing it.
        self.show_outliner()
        self.model.set_node_collapse(['/build'], True)
        app.processEvents()
        self.model.set_selection(['/build/rig/skeleton'])
        app.processEvents()
        self.assertFalse(self.outliner.items['/build'].isExpanded())
        self.assert_rows_match_the_graph()
        self.click_arrow('/build')
        self.assertFalse(self.model.get_node_collapse('/build'))
        self.assertTrue(self.outliner.items['/build'].isExpanded())

    def test_rows_match_the_graph_after_a_rebuild_and_undo(self):
        self.show_outliner()
        self.model.set_node_collapse(['/build/rig'], True)
        self.search('skel')
        self.search('')
        self.assert_rows_match_the_graph()
        self.model.undo_stack.undo()
        app.processEvents()
        self.assert_rows_match_the_graph()
        self.model.update_comp_layer(rebuild=True)
        app.processEvents()
        self.assert_rows_match_the_graph()

    def test_a_node_a_lower_layer_collapsed_expands_on_the_first_toggle(self):
        # Shown collapsed because a layer below says so, the top layer
        # saying nothing: the first toggle has to expand it.
        self.show_outliner()
        self.model.comp_layer.collapse['/build'] = True
        self.model.top_layer.collapse.pop('/build', None)
        self.model.collapse_changed.emit(['/build'])
        app.processEvents()
        self.assertFalse(self.outliner.items['/build'].isExpanded())
        self.double_click('/build')
        self.assertFalse(self.model.get_node_collapse('/build'))
        self.assertTrue(self.outliner.items['/build'].isExpanded())


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

    def test_edits_made_while_it_is_off_are_drawn_when_it_is_back(self):
        view = self.win.view
        action = self.win.app_actions.stage_view_action
        self.window_action(action, False)
        model = self.win.model
        with mock.patch.object(view, 'draw_graph') as draw:
            model.add_node(name='unseen', pos=[0, 0])
            model.set_node_collapse(['/build'], True)
            app.processEvents()
        # Nothing drawn for nobody.
        draw.assert_not_called()
        self.assertIsNone(view.get_node_graphic('/unseen'))
        self.window_action(action, True)
        self.assertIsNotNone(view.get_node_graphic('/unseen'))
        self.assertIsNone(view.get_node_graphic('/build/rig'))


if __name__ == '__main__':
    unittest.main()
