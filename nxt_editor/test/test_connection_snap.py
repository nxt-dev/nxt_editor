"""A line dragged out of a plug connects to the nearest plug that takes it
when dropped close by, not only when dropped right on one."""
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
from nxt import DATA_STATE
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {
    'version': '1.17', 'alias': 'snap',
    'nodes': {'/a': {'attrs': {'out': {'type': 'raw', 'value': '1'}}},
              '/b': {'attrs': {'take': {'type': 'raw', 'value': '2'}}}},
    'meta_data': {'positions': {'/a': [0.0, 0.0], '/b': [500.0, 0.0]}},
}


class DroppingNearAPlug(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_snap_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'snap.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        # Room for both nodes whatever layout an earlier window saved.
        self.win.resize(1400, 900)
        self.docks = [d for d in self.win.findChildren(QtWidgets.QDockWidget)
                      if d.isVisible()]
        for dock in self.docks:
            dock.hide()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        self.model.set_attr_display_state(['/a', '/b'], 3)
        app.processEvents()
        # Plugs are made as their node is first drawn up close.
        self.zoom(1)

    def tearDown(self):
        # Shown again, so the layout the window saves is the one it had.
        for dock in self.docks:
            dock.show()
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def zoom(self, scale):
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.view.centerOn(250, 0)
        app.processEvents()
        self.view.viewport().repaint()
        app.processEvents()

    def plug(self, node_path, attr, side):
        """A plug, as where it is in the scene and how big."""
        graphic = self.view.get_node_graphic(node_path)
        if attr == 'exec':
            attr = '_execute_in'
            radius = graphic.EXEC_PLUG_RADIUS
        else:
            radius = graphic.ATTR_PLUG_RADIUS
        if side == 'in':
            pos = graphic.get_attr_in_pos(attr, scene=True)
        else:
            pos = graphic.get_attr_out_pos(attr, scene=True)
        return pos, radius

    def mouse(self, kind, view_pos):
        local = QtCore.QPointF(view_pos)
        if kind == QtCore.QEvent.MouseButtonPress:
            button, held = QtCore.Qt.LeftButton, QtCore.Qt.LeftButton
        elif kind == QtCore.QEvent.MouseMove:
            button, held = QtCore.Qt.NoButton, QtCore.Qt.LeftButton
        else:
            button, held = QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        event = QtGui.QMouseEvent(kind, local, self.view.mapToGlobal(local),
                                  button, held, QtCore.Qt.NoModifier)
        handler = {QtCore.QEvent.MouseButtonPress: self.view.mousePressEvent,
                   QtCore.QEvent.MouseMove: self.view.mouseMoveEvent,
                   QtCore.QEvent.MouseButtonRelease:
                       self.view.mouseReleaseEvent}[kind]
        handler(event)
        app.processEvents()

    def screen_pos(self, plug):
        return QtCore.QPointF(self.view.mapFromScene(plug[0]))

    def drag(self, start_plug, end_plug, off_pixels, release=True):
        """Drag out of start_plug to a spot off_pixels on screen to the
        right of end_plug's edge."""
        start = self.screen_pos(start_plug)
        edge = end_plug[1] * self.view.scale_factor
        end = self.screen_pos(end_plug) + QtCore.QPointF(edge + off_pixels,
                                                         0)
        self.mouse(QtCore.QEvent.MouseButtonPress, start)
        self.assertIsNotNone(self.view.potential_connection)
        self.mouse(QtCore.QEvent.MouseMove, (start + end) * .5)
        self.mouse(QtCore.QEvent.MouseMove, end)
        if release:
            self.mouse(QtCore.QEvent.MouseButtonRelease, end)

    def value(self):
        return self.model.get_node_attr_value('/b', 'take',
                                              self.model.comp_layer,
                                              data_state=DATA_STATE.RAW)

    def test_dropping_a_few_pixels_off_connects_zoomed_out(self):
        self.zoom(.5)
        self.drag(self.plug('/a', 'out', 'out'), self.plug('/b', 'take', 'in'),
                  8)
        self.assertEqual('${/a.out}', self.value())

    def test_dropping_a_few_pixels_off_connects_zoomed_in(self):
        self.zoom(1.5)
        self.drag(self.plug('/a', 'out', 'out'), self.plug('/b', 'take', 'in'),
                  8)
        self.assertEqual('${/a.out}', self.value())

    def test_dropping_further_off_does_not_connect(self):
        self.zoom(.5)
        self.drag(self.plug('/a', 'out', 'out'), self.plug('/b', 'take', 'in'),
                  40)
        self.assertEqual('2', self.value())

    def test_dragging_from_an_input_snaps_to_an_output(self):
        self.zoom(.5)
        self.drag(self.plug('/b', 'take', 'in'), self.plug('/a', 'out', 'out'),
                  8)
        self.assertEqual('${/a.out}', self.value())

    def test_an_exec_line_snaps_to_an_exec_plug(self):
        self.zoom(.5)
        self.drag(self.plug('/a', 'exec', 'out'), self.plug('/b', 'exec', 'in'),
                  8)
        self.assertEqual('/a', self.model.get_node_exec_in('/b'))

    def test_a_property_line_does_not_snap_to_an_exec_plug(self):
        self.zoom(.5)
        self.drag(self.plug('/a', 'out', 'out'), self.plug('/b', 'exec', 'in'),
                  2, release=False)
        self.assertIsNone(self.view.snap_plug)

    def test_the_plug_it_would_snap_to_is_marked_and_the_line_ends_on_it(self):
        self.zoom(.5)
        take = self.plug('/b', 'take', 'in')
        self.drag(self.plug('/a', 'out', 'out'), take, 8, release=False)
        target = self.view.snap_plug
        self.assertEqual(('/b', 'take', True),
                         (target.node_path, target.attr_name,
                          target.is_input))
        self.assertEqual(take[0], self.view.potential_connection.tgt_pos)
        # Away again, it lets go.
        self.mouse(QtCore.QEvent.MouseMove,
                   self.screen_pos(take) + QtCore.QPointF(200, 0))
        self.assertIsNone(self.view.snap_plug)
        self.assertEqual(self.view.mouse_scene_pos,
                         self.view.potential_connection.tgt_pos)
        self.mouse(QtCore.QEvent.MouseButtonRelease,
                   self.screen_pos(take) + QtCore.QPointF(200, 0))
        self.assertIsNone(self.view.potential_connection)
        self.assertEqual('2', self.value())

    def test_its_ring_is_drawn(self):
        self.zoom(.5)
        take = self.plug('/b', 'take', 'in')
        self.drag(self.plug('/a', 'out', 'out'), take, 8, release=False)
        painter = mock.Mock()
        self.view.draw_snap_plug(painter)
        self.assertTrue(painter.drawEllipse.called)
        center = painter.drawEllipse.call_args[0][0]
        self.assertEqual(take[0], center)


if __name__ == '__main__':
    unittest.main()
