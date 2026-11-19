"""The graph has no edge.

The scene rect used to be fixed at 10000 units square, so panning stopped
at its edge, and framing, Go to Node and bookmarks could not center past
it. It now grows ahead of the view, a few times however far it goes.
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
from nxt_editor import colors, stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

FAR = 60000


class Canvas(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_canvas_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'far.nxt')
        with open(path, 'w') as fp:
            json.dump({'version': '1.17', 'alias': 'far',
                       'nodes': {'/home': {}, '/far': {}}}, fp)
        self.win = MainWindow(filepath=path)
        self.win.resize(1200, 800)
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

    def center(self):
        viewport = self.view.viewport().rect()
        return self.view.mapToScene(viewport.center())

    def assertNear(self, point, other, pixels=3):
        # Within a few pixels on screen, at whatever zoom.
        slack = pixels / self.view.scale_factor
        self.assertLess(abs(point.x() - other.x()), slack, (point, other))
        self.assertLess(abs(point.y() - other.y()), slack, (point, other))

    def pan(self, dx, dy, steps):
        view = self.view
        view.start_panning()
        pos = QtCore.QPointF(600, 400)
        for _ in range(steps):
            pos += QtCore.QPointF(-dx, -dy)
            event = QtGui.QMouseEvent(
                QtCore.QEvent.MouseMove, pos, view.mapToGlobal(pos.toPoint()),
                QtCore.Qt.NoButton, QtCore.Qt.MiddleButton,
                QtCore.Qt.NoModifier)
            view.mouseMoveEvent(event)
        view.stop_panning()

    def test_the_view_centers_anywhere(self):
        for target in (QtCore.QPointF(FAR, -FAR), QtCore.QPointF(-FAR, FAR)):
            self.view.centerOn(target)
            self.assertNear(target, self.center())

    def test_panning_goes_on_past_where_the_edge_was(self):
        start = self.center()
        scene = self.view.scene()
        grew = mock.patch.object(scene, 'setSceneRect',
                                 wraps=scene.setSceneRect)
        with grew as grow:
            self.pan(200, 0, 600)
        # About 120000 pixels, far past the old edge at 5000. The first
        # move only marks where the drag starts.
        moved = 200 * 599 / self.view.scale_factor
        self.assertNear(start + QtCore.QPointF(moved, 0), self.center())
        # It grows a few times, not on every move.
        self.assertLess(grow.call_count, 10)

    def test_zooming_out_far_away_keeps_the_point_under_the_mouse(self):
        self.view.centerOn(FAR, FAR)
        corner = QtCore.QPoint(50, 50)
        under = self.view.mapToScene(corner)
        for _ in range(30):
            event = QtGui.QWheelEvent(
                QtCore.QPointF(corner), QtCore.QPointF(
                    self.view.mapToGlobal(corner)),
                QtCore.QPoint(), QtCore.QPoint(0, -120),
                QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                QtCore.Qt.NoScrollPhase, False)
            self.view.wheelEvent(event)
        self.assertAlmostEqual(self.view._scale_minimum,
                               self.view.scale_factor, delta=0.05)
        # Scroll positions are whole pixels, so each of the 30 steps can
        # round by one, here as at the origin.
        self.assertNear(under, self.view.mapToScene(corner), pixels=12)

    def test_framing_a_node_far_away_shows_it(self):
        graphic = self.view.get_node_graphic('/far')
        graphic.setPos(FAR, -FAR)
        self.view.frame_nodes(['/far'])
        app.processEvents()
        self.assertTrue(self.view.view_rect().contains(
            graphic.sceneBoundingRect()))
        self.assertNear(graphic.sceneBoundingRect().center(), self.center())

    def test_the_canvas_is_drawn_where_the_edge_was(self):
        self.view.centerOn(FAR, FAR)
        app.processEvents()
        self.assertTrue(self.view.sceneRect().contains(
            self.view.view_rect()))
        image = self.view.viewport().grab().toImage()
        canvas = colors.GRAPH_BG_COLOR.rgb()
        patch = [image.pixel(x, y) for x in range(5, 45)
                 for y in range(5, 45)]
        # Mostly the canvas color, between grid lines, not the empty
        # brush the view shows outside the scene.
        self.assertGreater(patch.count(canvas), len(patch) // 2)


if __name__ == '__main__':
    unittest.main()
