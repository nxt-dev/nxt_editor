"""Lining up nodes and the points lines are routed through."""
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
from nxt_editor import align, stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

LINE = '/a>/b._execute_in'
GRAPH = {
    'version': '1.17', 'alias': 'align',
    'nodes': {'/a': {}, '/b': {'execute_in': '/a'}, '/c': {}},
    'meta_data': {'positions': {'/a': [0.0, 0.0], '/b': [400.0, 100.0],
                                '/c': [100.0, 300.0]},
                  'connection_points': {LINE: [[250.0, 50.0]]}},
}


class Geometry(unittest.TestCase):

    BOXES = {'a': (0, 0, 100, 40), 'b': (300, 100, 380, 120),
             'p': (200, 60, 200, 60)}

    def test_left_moves_everything_to_the_left_most(self):
        offsets = align.align_offsets(self.BOXES, align.LEFT)
        self.assertEqual({'b': (-300, 0.0), 'p': (-200, 0.0)}, offsets)

    def test_right_moves_everything_to_the_right_most(self):
        offsets = align.align_offsets(self.BOXES, align.RIGHT)
        self.assertEqual({'a': (280, 0.0), 'p': (180, 0.0)}, offsets)

    def test_middles_meet_in_the_middle_of_them_all(self):
        offsets = align.align_offsets(self.BOXES, align.VCENTER)
        self.assertEqual((0.0, 40.0), offsets['a'])
        self.assertEqual((0.0, -50.0), offsets['b'])
        self.assertEqual((0.0, 0.0), offsets.get('p', (0.0, 0.0)))

    def test_bottom_lines_up_bottoms(self):
        offsets = align.align_offsets(self.BOXES, align.BOTTOM)
        self.assertEqual({'a': (0.0, 80), 'p': (0.0, 60)}, offsets)

    def test_one_thing_does_not_move(self):
        self.assertEqual({}, align.align_offsets({'a': (0, 0, 1, 1)},
                                                 align.LEFT))

    def test_distribute_leaves_the_ends_and_evens_the_gaps(self):
        boxes = {'a': (0, 0, 100, 10), 'b': (110, 0, 130, 10),
                 'c': (300, 0, 400, 10)}
        offsets = align.distribute_offsets(boxes, align.HORIZONTAL)
        # 200 between a and c, less b's 20, is two gaps of 90.
        self.assertEqual({'b': (80, 0.0)}, offsets)

    def test_distribute_needs_three(self):
        boxes = {'a': (0, 0, 1, 1), 'b': (5, 5, 6, 6)}
        self.assertEqual({}, align.distribute_offsets(boxes, align.VERTICAL))


class InTheView(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_align_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'align.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        app.processEvents()

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def top(self, path):
        return self.view.layout_boxes()[('node', path)][1]

    def test_nodes_and_a_point_line_up_on_top_in_one_undo(self):
        self.model.set_selection(['/b', '/c'])
        self.view.select_points([(LINE, 0)])
        before = self.model.undo_stack.count()
        self.win.alignment_actions.align_top_action.trigger()
        app.processEvents()
        self.assertEqual(before + 1, self.model.undo_stack.count())
        self.assertEqual(self.model.get_line_points(LINE)[0][1],
                         self.top('/b'))
        self.assertAlmostEqual(self.top('/b'), self.top('/c'))
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([[250.0, 50.0]], self.model.get_line_points(LINE))

    def test_distribute_spaces_nodes_out(self):
        self.model.set_selection(['/a', '/b', '/c'])
        self.win.alignment_actions.distribute_vertical_action.trigger()
        app.processEvents()
        boxes = self.view.layout_boxes()
        a, b, c = (boxes[('node', p)] for p in ('/a', '/b', '/c'))
        self.assertAlmostEqual(b[1] - a[3], c[1] - b[3], places=3)

    def test_the_right_click_menu_has_align_in_the_middle(self):
        self.model.set_selection(['/a', '/b'])
        menu = self.view.node_menu()
        titles = [a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertIn('Align', titles)
        index = titles.index('Align')
        self.assertTrue(0 < index < len(titles) - 1)
        submenu = [a for a in menu.actions() if a.text() == 'Align'][0]
        self.assertTrue(submenu.isEnabled())

    def test_align_is_greyed_out_with_one_thing_selected(self):
        self.model.set_selection(['/a'])
        menu = self.view.node_menu()
        submenu = [a for a in menu.actions() if a.text() == 'Align'][0]
        self.assertFalse(submenu.isEnabled())

    def test_the_toolbar_has_align_before_select_all(self):
        toolbar = self.win.authoring_toolbar
        actions = toolbar.actions()
        select_all = self.win.node_actions.select_all_action
        button = toolbar.widgetForAction(actions[actions.index(
            select_all) - 1])
        self.assertIs(toolbar.align_button, button)
        self.assertFalse(select_all.icon().isNull())
        self.assertIn('Select all nodes', select_all.toolTip())


if __name__ == '__main__':
    unittest.main()
