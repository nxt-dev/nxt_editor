"""Layout Nodes: top level nodes arranged by the order they run in, each
exec chain left to right and its branches stacked below, as one undo."""
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
from nxt_editor import auto_layout, backdrops, stage_model
from nxt_editor.dockwidgets.outliner import root_exec_order

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class Grid(unittest.TestCase):

    def test_a_chain_runs_left_to_right(self):
        cells = auto_layout.grid(['/a', '/b', '/c'],
                                 {'/b': '/a', '/c': '/b'})
        self.assertEqual({'/a': (0, 0), '/b': (1, 0), '/c': (2, 0)}, cells)

    def test_branches_stack_below_and_finish_before_the_next(self):
        # /a runs /b and /e. /b runs /c and /d.
        exec_in = {'/b': '/a', '/c': '/b', '/d': '/b', '/e': '/a'}
        cells = auto_layout.grid(['/a', '/b', '/c', '/d', '/e'], exec_in)
        self.assertEqual((0, 0), cells['/a'])
        self.assertEqual((1, 0), cells['/b'])
        self.assertEqual((2, 0), cells['/c'])
        self.assertEqual((2, 1), cells['/d'])
        self.assertEqual((1, 2), cells['/e'])

    def test_nodes_on_no_chain_get_a_row_each_in_order(self):
        cells = auto_layout.grid(['/x', '/y'], {})
        self.assertEqual({'/x': (0, 0), '/y': (0, 1)}, cells)

    def test_a_source_outside_the_nodes_starts_a_chain(self):
        cells = auto_layout.grid(['/b', '/c'], {'/b': '/a', '/c': '/b'})
        self.assertEqual({'/b': (0, 0), '/c': (1, 0)}, cells)

    def test_a_loop_is_still_laid_out(self):
        cells = auto_layout.grid(['/a', '/b'], {'/a': '/b', '/b': '/a'})
        self.assertEqual({'/a': (0, 0), '/b': (1, 0)}, cells)

    def test_columns_and_rows_fit_the_largest(self):
        places = auto_layout.arrange(
            ['/a', '/b', '/c'], {'/b': '/a'},
            {'/a': (100, 50), '/b': (60, 30), '/c': (200, 80)},
            gap_x=10, gap_y=5)
        self.assertEqual((0.0, 0.0), places['/a'])
        # Column 0 is as wide as /c, the widest in it.
        self.assertEqual((210.0, 0.0), places['/b'])
        self.assertEqual((0.0, 55.0), places['/c'])

    def test_a_long_chain_does_not_run_out_of_stack(self):
        paths = ['/n{}'.format(i) for i in range(3000)]
        exec_in = dict((paths[i], paths[i - 1]) for i in range(1, 3000))
        cells = auto_layout.grid(paths, exec_in)
        self.assertEqual((2999, 0), cells[paths[-1]])


# /start runs /second and /later. The one of them that runs first carries
# on along the row, the other starts the row below.
GRAPH = {
    'version': '1.17', 'alias': 'layout',
    'nodes': {'/start': {'start_point': True},
              '/second': {'execute_in': '/start'},
              '/later': {'execute_in': '/start'},
              '/third': {'execute_in': '/second'},
              '/loose': {},
              '/kept': {}},
    'meta_data': {
        'positions': {'/start': [900.0, 900.0], '/second': [100.0, 50.0],
                      '/later': [-300.0, 700.0], '/third': [50.0, 500.0],
                      '/loose': [400.0, 400.0], '/kept': [2000.0, 2000.0]},
        'backdrops': {'bd_one': backdrops.make((340.0, 300.0),
                                               (300.0, 300.0))}},
}


class InTheView(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_layout_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'layout.nxt')
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

    def rect(self, path):
        return self.view._nodes_rect([self.view.get_node_graphic(path)])

    def test_selected_nodes_follow_their_build_in_one_undo(self):
        paths = ['/start', '/second', '/later', '/third']
        self.model.set_selection(paths)
        before = self.model.undo_stack.count()
        self.win.alignment_actions.layout_action.trigger()
        app.processEvents()
        self.assertEqual(before + 1, self.model.undo_stack.count())
        first, other = [p for p in root_exec_order(self.model)
                        if p in ('/second', '/later')]
        start, row, branch = (self.rect(p) for p in ('/start', first, other))
        # Left to right along the chain, on one row.
        self.assertLess(start.right(), row.left())
        self.assertAlmostEqual(start.top(), row.top())
        # /third carries on after /second, on its row.
        second, third = self.rect('/second'), self.rect('/third')
        self.assertLess(second.right(), third.left())
        self.assertAlmostEqual(second.top(), third.top())
        # The branch below, in the column after /start.
        self.assertAlmostEqual(row.left(), branch.left())
        self.assertGreater(branch.top(), row.bottom())
        # They start where the top left of them all was.
        self.assertAlmostEqual(-300.0, round(start.left(), -1), delta=20)
        # What was not selected stays.
        self.assertEqual([2000.0, 2000.0], self.model.get_node_pos('/kept'))
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([900.0, 900.0], self.model.get_node_pos('/start'))

    def test_with_nothing_selected_it_lays_out_everything(self):
        self.model.set_selection([])
        self.view.layout_nodes()
        app.processEvents()
        rects = [self.rect(p) for p in GRAPH['nodes']]
        for i, one in enumerate(rects):
            for other in rects[i + 1:]:
                self.assertFalse(one.intersects(other))
        self.assertNotEqual([2000.0, 2000.0],
                            self.model.get_node_pos('/kept'))

    def test_a_backdrop_is_fitted_around_its_nodes(self):
        self.model.set_selection([])
        self.view.layout_nodes()
        app.processEvents()
        graphic = self.view.get_backdrop_graphic('bd_one')
        self.assertTrue(graphic.scene_rect().contains(self.rect('/loose')))

    def test_it_is_in_the_graph_menu_and_the_right_click_menus(self):
        action = self.win.alignment_actions.layout_action
        self.assertIn(action, self.win.menu_bar.graph_menu.actions())
        self.model.set_selection([])
        self.assertIn(action, self.view.node_menu().actions())
        self.model.set_selection(['/start'])
        self.assertIn(action, self.view.node_menu('/start').actions())


if __name__ == '__main__':
    unittest.main()
