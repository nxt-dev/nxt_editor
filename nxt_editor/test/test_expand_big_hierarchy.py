"""Expanding a big hierarchy at once, with Shift in the graph or the
Outliner, draws it in one pass.

Every node in it is named in the change, and the graph used to draw each
one's descendants as it came, laying the whole tree out and redrawing its
lines again for every node, so expanding took minutes on a big hierarchy.
A big one is also shown as it is drawn, rather than the window freezing.
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
from nxt_editor import stage_model, user_dir
from nxt_editor.stage_view import StageView

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

DEPTH, WIDE = 3, 7  # 400 nodes, more than StageView.PROGRESSIVE_DRAW


def hierarchy():
    nodes = {}

    def add(path, depth):
        nodes[path] = {}
        if depth < DEPTH:
            for i in range(WIDE):
                add('{}/c{}'.format(path, i), depth + 1)
    add('/rig', 0)
    return nodes


class ExpandBig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_expand_big_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.nodes = hierarchy()
        path = os.path.join(self.tmp, 'big.nxt')
        with open(path, 'w') as fp:
            json.dump({'version': '1.17', 'alias': 'big',
                       'nodes': self.nodes}, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.view = self.win.view

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()

    def positions(self):
        return {path: graphic.scenePos()
                for path, graphic in self.view._node_graphics.items()
                if graphic}

    def collapse_all(self):
        self.model.toggle_node_collapse(['/rig'], recursive_down=True)
        app.processEvents()
        self.assertTrue(self.model.get_node_collapse('/rig'))
        self.assertEqual(['/rig'], list(self.view._node_graphics))

    def test_a_shift_expand_draws_everything_once(self):
        before = self.positions()
        self.assertEqual(len(self.nodes), len(before))
        self.collapse_all()
        drawn = mock.patch.object(StageView, 'handle_nodes_changed',
                                  autospec=True,
                                  side_effect=StageView.handle_nodes_changed)
        with drawn as handle:
            self.view.get_node_graphic('/rig').collapse_node(recursive=True)
        app.processEvents()
        self.assertEqual(1, handle.call_count)
        self.assertFalse(self.model.get_node_collapse('/rig'))
        after = self.positions()
        self.assertEqual(set(before), set(after))
        for path, pos in before.items():
            self.assertEqual(pos, after[path], path)

    def test_the_outliner_expands_the_same_way(self):
        before = self.positions()
        self.collapse_all()
        outliner = self.win.outliner
        outliner.show()
        app.processEvents()
        # Its rows are open by the time the graph starts drawing.
        rows_open = []
        real = StageView.handle_collapse_changed

        def graph_hears(view, paths):
            rows_open.append(outliner.items['/rig/c0/c0'].isExpanded())
            return real(view, paths)
        with mock.patch.object(StageView, 'handle_collapse_changed',
                               autospec=True, side_effect=graph_hears):
            outliner.toggle_collapse('/rig', QtCore.Qt.ShiftModifier)
        app.processEvents()
        self.assertEqual([True], rows_open)
        self.assertEqual(before, self.positions())
        self.assertTrue(all(item.isExpanded()
                            for item in outliner.items.values()
                            if item.childCount()))

    def test_a_big_expand_is_shown_as_it_goes(self):
        self.collapse_all()
        shown = []
        real = QtWidgets.QApplication.processEvents

        def process(*args):
            shown.append(len(self.view._node_graphics))
            real(*args)
        times = iter(range(1000))
        with mock.patch.object(QtWidgets.QApplication, 'processEvents',
                               side_effect=process), \
                mock.patch('nxt_editor.stage_view.time.time',
                           side_effect=lambda: next(times)):
            self.view.get_node_graphic('/rig').collapse_node(recursive=True)
        partway = [count for count in shown if 1 < count < len(self.nodes)]
        self.assertTrue(partway, shown)


class HoldingPrefs(unittest.TestCase):

    def test_a_pref_file_is_looked_at_once_while_held(self):
        prefs = user_dir.JsonPref(os.path.join(
            tempfile.mkdtemp(prefix='nxt_held_'), 'prefs.json'))
        self.addCleanup(shutil.rmtree, os.path.dirname(prefs.path),
                        ignore_errors=True)
        prefs['a'] = 1
        prefs.get('a')
        with mock.patch('nxt_editor.user_dir.os.stat',
                        side_effect=os.stat) as stat:
            with user_dir.holding_prefs():
                for _ in range(5):
                    self.assertEqual(1, prefs.get('a'))
            self.assertEqual(0, stat.call_count)
            prefs.get('a')
            self.assertEqual(1, stat.call_count)

    def test_a_write_while_held_is_read_back(self):
        prefs = user_dir.JsonPref(os.path.join(
            tempfile.mkdtemp(prefix='nxt_held_'), 'prefs.json'))
        self.addCleanup(shutil.rmtree, os.path.dirname(prefs.path),
                        ignore_errors=True)
        prefs['a'] = 1
        with user_dir.holding_prefs():
            prefs.get('a')
            prefs['a'] = 2
            self.assertEqual(2, prefs.get('a'))


if __name__ == '__main__':
    unittest.main()
