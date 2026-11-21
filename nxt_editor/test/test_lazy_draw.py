"""A big graph draws the nodes in view first and the rest while the editor
is idle, and ends up drawn exactly as when it is drawn all at once.

The thresholds are turned down here so a small graph takes that path.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt_editor import stage_model
from nxt_editor.stage_view import StageView

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

ROOTS = 30


def graph():
    """Roots in a row, each with two children, run one after another, with
    attrs that read the root before, and every fifth instancing the first."""
    nodes = {}
    positions = {}
    for i in range(ROOTS):
        root = '/r{}'.format(i)
        data = {'attrs': {'speed': {'value': str(i)}}}
        if i:
            data['execute_in'] = '/r{}'.format(i - 1)
            data['attrs']['from_before'] = {
                'value': '${/r%d.speed}' % (i - 1)}
        if i and i % 5 == 0:
            data['instance'] = '/r0'
        nodes[root] = data
        nodes[root + '/a'] = {}
        nodes[root + '/b'] = {}
        # Far apart, so only some are in view at once.
        positions[root] = [i * 900.0, (i % 3) * 600.0]
    return {'version': '1.17', 'alias': 'lazy', 'references': [],
            'meta_data': {'positions': positions}, 'nodes': nodes}


class LazyDraw(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_lazy_draw_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'lazy.nxt')
        with open(self.path, 'w') as fp:
            json.dump(graph(), fp)

    def open(self, lazy):
        over = 10 if lazy else 10 ** 9
        patches = [mock.patch.object(StageView, 'LAZY_DRAW_OVER', over),
                   mock.patch.object(StageView, 'FIRST_DRAW', 12)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        win = MainWindow(filepath=self.path)
        win.resize(1200, 800)
        win.show()
        # Held, so the tests see nodes waiting: drain lets them be drawn.
        win.view._pending_timer.stop()
        app.processEvents()
        win.view._pending_timer.stop()
        self.addCleanup(self.close, win)
        return win

    @staticmethod
    def close(win):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            win.close()
            app.processEvents()

    @staticmethod
    def drain(win):
        end = time.time() + 60
        while win.view.drawing and time.time() < end:
            if not win.view._pending_timer.isActive():
                win.view._pending_timer.start()
            app.processEvents()

    @staticmethod
    def drawn(win):
        view = win.view
        nodes = {path: (round(g.scenePos().x(), 2), round(g.scenePos().y(), 2))
                 for path, g in view._node_graphics.items()}
        lines = sorted((g.src_path, g.tgt_path)
                       for g in view._connection_graphics)
        return nodes, lines

    def test_some_nodes_wait_and_all_are_drawn_the_same(self):
        lazy = self.open(lazy=True)
        self.assertTrue(lazy.view.drawing)
        waiting = len(lazy.view._pending_root_of)
        self.assertTrue(waiting)
        self.drain(lazy)
        self.assertFalse(lazy.view.drawing)
        whole = self.open(lazy=False)
        self.assertEqual(len(whole.view._node_graphics),
                         len(lazy.view._node_graphics))
        self.assertFalse(whole.view.drawing)
        self.assertEqual(self.drawn(whole), self.drawn(lazy))

    def test_a_waiting_node_asked_for_is_drawn_then(self):
        win = self.open(lazy=True)
        waiting = sorted(win.view._pending_root_of)
        self.assertTrue(waiting)
        child = [p for p in waiting if p.endswith('/a')][0]
        graphic = win.view.get_node_graphic(child)
        self.assertIsNotNone(graphic)
        self.assertEqual(child, graphic.node_path)
        self.assertNotIn(child, win.view._pending_root_of)

    def test_selecting_a_waiting_node_selects_it(self):
        win = self.open(lazy=True)
        root = next(iter(win.view._pending_draw))
        win.model.set_selection([root])
        app.processEvents()
        self.assertTrue(win.view.get_node_graphic(root).isSelected())

    def test_select_all_selects_every_node(self):
        whole = self.open(lazy=False)
        whole.view.select_all()
        win = self.open(lazy=True)
        self.assertTrue(win.view.drawing)
        win.view.select_all()
        self.assertFalse(win.view.drawing)
        self.assertEqual(sorted(whole.model.selection),
                         sorted(win.model.selection))

    def test_framed_on_open_as_when_drawn_at_once(self):
        lazy = self.open(lazy=True)
        self.drain(lazy)
        whole = self.open(lazy=False)
        self.assertEqual(whole.view._frame_state(),
                         lazy.view._frame_state())

    def test_a_view_moved_while_drawing_stays_put(self):
        win = self.open(lazy=True)
        win.view.scale(2.0, 2.0)
        moved = win.view._frame_state()
        self.drain(win)
        self.assertEqual(moved, win.view._frame_state())

    def test_a_waiting_node_deleted_is_not_drawn(self):
        win = self.open(lazy=True)
        root = list(win.view._pending_draw)[-1]
        win.model.delete_nodes([root])
        app.processEvents()
        self.drain(win)
        self.assertNotIn(root, win.view._node_graphics)
        self.assertNotIn(root + '/a', win.view._node_graphics)

    def test_a_hidden_view_waits_until_shown(self):
        win = self.open(lazy=True)
        win.view.hide()
        before = len(win.view._node_graphics)
        end = time.time() + 1
        while time.time() < end:
            app.processEvents()
        self.assertEqual(before, len(win.view._node_graphics))
        self.assertTrue(win.view.drawing)
        win.view.show()
        self.drain(win)
        self.assertFalse(win.view.drawing)
        whole = self.open(lazy=False)
        self.assertEqual(sorted(whole.view._node_graphics),
                         sorted(win.view._node_graphics))
