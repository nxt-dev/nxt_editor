"""Holding Space turns a left drag in the graph into panning, for anyone
without a middle button."""
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
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {
    'version': '1.17', 'alias': 'pan',
    'nodes': {'/a': {}},
    'meta_data': {'positions': {'/a': [0.0, 0.0]}},
}


class PanKey(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_pan_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'pan.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        self.view.centerOn(0, 0)
        app.processEvents()

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def key(self, kind, key=QtCore.Qt.Key_Space, repeat=False):
        event = QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier, '', repeat)
        if kind == QtCore.QEvent.KeyPress:
            self.view.keyPressEvent(event)
        else:
            self.view.keyReleaseEvent(event)
        app.processEvents()

    def mouse(self, kind, view_pos, button=QtCore.Qt.LeftButton):
        local = QtCore.QPointF(*view_pos)
        if kind == QtCore.QEvent.MouseButtonPress:
            pressed, held = button, button
        elif kind == QtCore.QEvent.MouseMove:
            pressed, held = QtCore.Qt.NoButton, button
        else:
            pressed, held = button, QtCore.Qt.NoButton
        event = QtGui.QMouseEvent(kind, local, self.view.mapToGlobal(local),
                                  pressed, held, QtCore.Qt.NoModifier)
        handler = {QtCore.QEvent.MouseButtonPress: self.view.mousePressEvent,
                   QtCore.QEvent.MouseMove: self.view.mouseMoveEvent,
                   QtCore.QEvent.MouseButtonRelease:
                       self.view.mouseReleaseEvent}[kind]
        handler(event)
        app.processEvents()

    def drag(self, start, end, button=QtCore.Qt.LeftButton):
        self.mouse(QtCore.QEvent.MouseButtonPress, start, button)
        self.mouse(QtCore.QEvent.MouseMove, start, button)
        self.mouse(QtCore.QEvent.MouseMove, end, button)
        self.mouse(QtCore.QEvent.MouseButtonRelease, end, button)

    def center(self):
        return self.view.mapToScene(self.view.viewport().rect().center())

    def node_view_pos(self):
        graphic = self.view.get_node_graphic('/a')
        pos = self.view.mapFromScene(graphic.sceneBoundingRect().center())
        return pos.x(), pos.y()

    def cursor(self):
        return self.view.viewport().cursor().shape()

    def test_space_and_a_left_drag_pans(self):
        before = self.center()
        self.key(QtCore.QEvent.KeyPress)
        self.drag((10, 10), (60, 40))
        self.key(QtCore.QEvent.KeyRelease)
        moved = before - self.center()
        self.assertAlmostEqual(50, moved.x() * self.view.scale_factor,
                               delta=1)
        self.assertAlmostEqual(30, moved.y() * self.view.scale_factor,
                               delta=1)
        self.assertFalse(self.view.panning)

    def test_on_a_node_it_pans_rather_than_moving_or_selecting_it(self):
        start = self.node_view_pos()
        self.key(QtCore.QEvent.KeyPress)
        self.drag(start, (start[0] + 80, start[1] + 50))
        self.key(QtCore.QEvent.KeyRelease)
        self.assertEqual([], self.model.selection)
        self.assertEqual([0.0, 0.0],
                         list(self.model.get_node_pos('/a')))

    def test_without_space_a_left_drag_does_not_pan(self):
        before = self.center()
        self.drag((10, 10), (60, 40))
        self.assertEqual(before, self.center())

    def test_a_middle_drag_still_pans(self):
        before = self.center()
        self.drag((10, 10), (60, 40), QtCore.Qt.MiddleButton)
        self.assertNotEqual(before, self.center())

    def test_the_cursor_is_a_hand(self):
        self.key(QtCore.QEvent.KeyPress)
        self.assertEqual(QtCore.Qt.OpenHandCursor, self.cursor())
        self.mouse(QtCore.QEvent.MouseButtonPress, (10, 10))
        self.assertEqual(QtCore.Qt.ClosedHandCursor, self.cursor())
        self.mouse(QtCore.QEvent.MouseButtonRelease, (10, 10))
        self.assertEqual(QtCore.Qt.OpenHandCursor, self.cursor())
        self.key(QtCore.QEvent.KeyRelease)
        self.assertEqual(QtCore.Qt.ArrowCursor, self.cursor())

    def test_a_repeated_release_while_held_keeps_it_ready(self):
        self.key(QtCore.QEvent.KeyPress)
        # Holding a key down sends repeated releases and presses.
        self.key(QtCore.QEvent.KeyRelease, repeat=True)
        self.key(QtCore.QEvent.KeyPress, repeat=True)
        self.assertEqual(QtCore.Qt.OpenHandCursor, self.cursor())
        before = self.center()
        self.drag((10, 10), (60, 40))
        self.assertNotEqual(before, self.center())


if __name__ == '__main__':
    unittest.main()
