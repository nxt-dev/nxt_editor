"""The Instance View: a node's instance connections, forwards and back.

It shows what the selected node instances from, back to the first source,
and every node that instances it, and theirs, and nothing else. Follow
Selection shows whichever node is selected, Show Selected shows it on
demand, and Sync Selection selects the nodes picked in it in the graph and
the Outliner too.
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
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt_editor import stage_model, user_dir
from nxt_editor.dockwidgets.instance_view import instance_lineage
from nxt_editor.dockwidgets.outliner import PATH_ROLE

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'inst', 'nodes': {
    '/base': {}, '/base/child': {},
    '/arm': {'instance': '/base'},
    '/arm_L': {'instance': '/arm'}, '/arm_R': {'instance': '/arm'},
    '/arm_L_twist': {'instance': '/arm_L'},
    '/leg': {'instance': '/base'},
    '/leg/child': {'attrs': {'side': {'value': 'L'}}}, '/loose': {}}}


class InstanceViewCase(unittest.TestCase):

    def setUp(self):
        prefs = (user_dir.USER_PREF.INSTANCE_VIEW_FOLLOW,
                 user_dir.USER_PREF.INSTANCE_VIEW_SYNC)
        saved = {key: (key in user_dir.user_prefs,
                       user_dir.user_prefs.get(key)) for key in prefs}

        def restore():
            for key, (had, value) in saved.items():
                if had:
                    user_dir.user_prefs[key] = value
                elif key in user_dir.user_prefs:
                    user_dir.user_prefs.pop(key)
        self.addCleanup(restore)
        for key in prefs:
            if key in user_dir.user_prefs:
                user_dir.user_prefs.pop(key)
        self.tmp = tempfile.mkdtemp(prefix='nxt_instance_view_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'inst.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.view = self.win.instance_view

    def tearDown(self):
        # Closed, as the editor saves its layout on close and the next
        # window would open with the view showing.
        self.view.hide()
        app.processEvents()
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def open_view(self):
        self.view.show()
        app.processEvents()
        self.assertTrue(self.view.isVisible())

    def select(self, paths):
        self.model.set_selection(paths)
        app.processEvents()


class Lineage(InstanceViewCase):

    def test_sources_back_and_instances_forward(self):
        columns, links = instance_lineage(self.model, '/arm')
        self.assertEqual({'/base': -1, '/arm': 0, '/arm_L': 1, '/arm_R': 1,
                          '/arm_L_twist': 2}, dict(columns))
        self.assertEqual(sorted([('/base', '/arm'), ('/arm', '/arm_L'),
                                 ('/arm', '/arm_R'),
                                 ('/arm_L', '/arm_L_twist')]), sorted(links))

    def test_nodes_sharing_a_source_are_not_its_connections(self):
        columns, _ = instance_lineage(self.model, '/arm')
        self.assertNotIn('/leg', columns)
        self.assertNotIn('/loose', columns)

    def test_a_node_with_none_is_shown_alone(self):
        columns, links = instance_lineage(self.model, '/loose')
        self.assertEqual({'/loose': 0}, dict(columns))
        self.assertEqual([], links)


class Showing(InstanceViewCase):

    def test_it_is_off_in_the_default_layout(self):
        # Once shown, the saved layout remembers it like any other dock.
        self.win.reset_layout()
        self.assertFalse(self.view.isVisible())

    def test_it_follows_the_selection(self):
        self.open_view()
        self.select(['/arm'])
        self.assertEqual(['/arm', '/arm_L', '/arm_L_twist', '/arm_R',
                          '/base'], sorted(self.view.items))
        self.select(['/leg'])
        self.assertEqual(['/base', '/leg'], sorted(self.view.items))

    def test_show_selected_when_not_following(self):
        self.open_view()
        self.view.follow_button.setChecked(False)
        self.select(['/arm_R'])
        self.assertEqual([], sorted(self.view.items))
        self.view.show_button.click()
        app.processEvents()
        self.assertEqual(['/arm', '/arm_R', '/base'],
                         sorted(self.view.items))

    def test_the_nodes_carry_their_layer_colors(self):
        self.open_view()
        self.select(['/arm'])
        item = self.view.items['/arm']
        self.assertEqual([self.model.get_layer_color(self.model.top_layer)],
                         item.layer_colors)

    def test_hidden_it_does_no_work(self):
        self.view.hide()
        app.processEvents()
        with mock.patch.object(self.view, 'rebuild') as rebuild:
            self.select(['/arm'])
            app.processEvents()
        rebuild.assert_not_called()
        self.open_view()
        self.assertIn('/arm_L', self.view.items)


class Striped(InstanceViewCase):
    """Proxy nodes, made by an instance with nothing of their own, are
    striped in the graph and the Outliner. An instance, or a node that
    overrides what its instance gives it, looks like any other node."""

    def test_proxies_are_marked_in_the_outliner(self):
        from nxt_editor.dockwidgets.outliner import INSTANCED_ROLE
        rows = self.win.outliner
        rows.show()
        app.processEvents()
        self.assertTrue(rows.items['/arm/child'].data(0, INSTANCED_ROLE))
        for path in ('/arm', '/arm_L_twist', '/leg/child', '/base',
                     '/base/child', '/loose'):
            self.assertFalse(rows.items[path].data(0, INSTANCED_ROLE), path)

    def test_proxies_are_striped_in_the_graph(self):
        view = self.win.view
        self.assertTrue(view.get_node_graphic('/arm/child').is_proxy)
        for path in ('/arm', '/leg/child', '/base/child'):
            self.assertFalse(view.get_node_graphic(path).is_proxy, path)

    def test_the_toolbar_runs_have_icons_and_tooltips(self):
        actions = self.win.execute_actions
        for action in (actions.execute_selected_action,
                       actions.execute_from_action,
                       actions.execute_hierarchy_action):
            self.assertFalse(action.icon().isNull(), action.text())
            self.assertIn(action.text().split()[0], action.toolTip())


class FocusIcon(InstanceViewCase):
    """The node the view is drawn from has a target, and only it."""

    def focused(self):
        return sorted(path for path, item in self.view.items.items()
                      if item.focus)

    def test_the_selected_node_has_it(self):
        self.open_view()
        self.select(['/arm'])
        self.assertEqual(['/arm'], self.focused())
        self.select(['/arm_L'])
        self.assertEqual(['/arm_L'], self.focused())

    def test_show_selected_moves_it(self):
        self.open_view()
        self.view.follow_button.setChecked(False)
        self.select(['/arm'])
        self.view.show_button.click()
        app.processEvents()
        self.assertEqual(['/arm'], self.focused())
        self.select(['/arm_R'])
        self.assertEqual(['/arm'], self.focused())
        self.view.show_button.click()
        app.processEvents()
        self.assertEqual(['/arm_R'], self.focused())

    def test_a_double_click_here_moves_it(self):
        from Qt import QtTest
        self.open_view()
        self.view.follow_button.setChecked(False)
        self.view.set_focus_path('/arm')
        app.processEvents()
        view = self.view.view
        item = self.view.items['/arm_R']
        center = item.mapToScene(item.boundingRect().center())
        QtTest.QTest.mouseDClick(view.viewport(), QtCore.Qt.LeftButton,
                                 QtCore.Qt.NoModifier,
                                 view.mapFromScene(center))
        app.processEvents()
        self.assertEqual('/arm_R', self.view.focus_path)
        self.assertEqual(['/arm_R'], self.focused())
        self.assertIn('drawn from', self.view.items['/arm_R'].toolTip())
        self.assertNotIn('drawn from', self.view.items['/arm'].toolTip())

    def test_the_target_is_drawn(self):
        from nxt_editor.dockwidgets.instance_view import (
            InstanceNodeItem, NODE_WIDTH, NODE_HEIGHT)

        def render(focus):
            item = InstanceNodeItem('/arm', ['#3166e4'], focus=focus)
            image = QtGui.QImage(NODE_WIDTH, NODE_HEIGHT,
                                 QtGui.QImage.Format_ARGB32)
            image.fill(QtCore.Qt.black)
            painter = QtGui.QPainter(image)
            item.paint(painter, QtWidgets.QStyleOptionGraphicsItem())
            painter.end()
            return image
        on, off = render(True), render(False)
        # Where the target sits, at the right end of the name.
        x, y = NODE_WIDTH - 17, 6 + 4 + 10
        self.assertNotEqual(on.pixel(x, y), off.pixel(x, y))


class Syncing(InstanceViewCase):

    def pick(self, paths):
        scene = self.view.view.scene()
        scene.clearSelection()
        for path in paths:
            self.view.items[path].setSelected(True)
        app.processEvents()

    def test_off_picking_here_leaves_the_graph_alone(self):
        self.open_view()
        self.select(['/arm'])
        self.pick(['/arm_L'])
        self.assertEqual(['/arm'], self.model.get_selected_nodes())

    def test_on_picking_here_selects_in_the_graph(self):
        self.open_view()
        self.view.sync_button.setChecked(True)
        self.select(['/arm'])
        self.pick(['/arm_L', '/arm_R'])
        self.assertEqual(['/arm_L', '/arm_R'],
                         sorted(self.model.get_selected_nodes()))
        # What is shown stays, rather than following its own selection.
        self.assertEqual('/arm', self.view.focus_path)
        rows = self.win.outliner
        rows.show()
        app.processEvents()
        selected = sorted(item.data(0, PATH_ROLE)
                          for item in rows.tree.selectedItems())
        self.assertEqual(['/arm_L', '/arm_R'], selected)

    def test_picked_nodes_are_framed_and_revealed(self):
        self.open_view()
        rows = self.win.outliner
        rows.show()
        app.processEvents()
        self.view.sync_button.setChecked(True)
        self.select(['/arm'])
        # Hidden in the Outliner: its group closed.
        heading = rows.items['/arm_L_twist'].parent()
        while heading.parent() is not None:
            heading = heading.parent()
        heading.setExpanded(False)
        framed = []
        self.model.frame_items.connect(framed.append)
        self.pick(['/arm_L_twist'])
        self.assertEqual([('/arm_L_twist',)], framed)
        self.assertTrue(heading.isExpanded())

    def test_the_buttons_are_icons_with_tooltips(self):
        for button in (self.view.show_button, self.view.follow_button,
                       self.view.sync_button):
            self.assertEqual('', button.text())
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.toolTip())

    def test_the_toggles_are_remembered(self):
        self.view.sync_button.setChecked(True)
        self.view.follow_button.setChecked(False)
        self.assertIs(True, user_dir.user_prefs.get(
            user_dir.USER_PREF.INSTANCE_VIEW_SYNC))
        self.assertIs(False, user_dir.user_prefs.get(
            user_dir.USER_PREF.INSTANCE_VIEW_FOLLOW))


if __name__ == '__main__':
    unittest.main()
