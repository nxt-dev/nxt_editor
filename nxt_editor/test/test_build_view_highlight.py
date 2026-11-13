"""Selecting or hovering a node in the build view outlines it.

The node that runs next is filled red. Hover used to paint the row grey
over that red. Now a selected node gets an amber edge and the row under
the mouse a white one, and the fill stays as it is.
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
from nxt_editor.dockwidgets.build_view import BuildModel, BuildView

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'build', 'nodes': {
    '/setup': {'start_point': True},
    '/build': {'execute_in': '/setup'},
    '/publish': {'execute_in': '/build'}}}


class Highlight(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_build_view_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'build.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.win.resize(1400, 900)
        self.view = self.win.findChild(BuildView)
        self.view.show()
        app.processEvents()
        self.table = self.view.findChild(QtWidgets.QTableView)
        self.model = self.win.model

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def pixel(self, row, where):
        app.processEvents()
        self.table.viewport().repaint()
        image = self.table.viewport().grab().toImage()
        rect = self.table.visualRect(
            self.table.model().index(row, BuildModel.PATH_COLUMN))
        point = {'inside': QtCore.QPoint(rect.right() - 20,
                                         rect.center().y()),
                 'edge': QtCore.QPoint(rect.right() - 20, rect.top() + 1)}
        return QtGui.QColor(image.pixel(point[where])).name()

    def test_the_next_node_stays_red_under_the_mouse(self):
        red = QtGui.QColor(QtCore.Qt.red).name()
        self.assertEqual(red, self.pixel(0, 'inside'))
        self.table.set_hover_row(0)
        self.assertEqual(red, self.pixel(0, 'inside'))
        self.model.set_selection(['/setup'])
        self.assertEqual(red, self.pixel(0, 'inside'))

    def test_selection_outlines_in_amber_and_hover_in_white(self):
        plain = self.pixel(1, 'edge')
        self.model.set_selection(['/build'])
        self.assertEqual(colors.SELECTED.name(), self.pixel(1, 'edge'))
        self.model.set_selection([])
        self.assertEqual(plain, self.pixel(1, 'edge'))
        self.table.set_hover_row(2)
        hovered = self.pixel(2, 'edge')
        self.assertNotEqual(plain, hovered)
        self.assertNotEqual(colors.SELECTED.name(), hovered)
        # Hover leaves the inside alone.
        self.assertEqual(self.pixel(1, 'inside'), self.pixel(2, 'inside'))


    def move_mouse(self, row, column):
        from Qt import QtTest
        rect = self.table.visualRect(self.table.model().index(row, column))
        QtTest.QTest.mouseMove(self.table.viewport(), rect.center())
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove, QtCore.QPointF(rect.center()),
            QtCore.QPointF(self.table.viewport().mapToGlobal(rect.center())),
            QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        self.table.mouseMoveEvent(event)

    def test_only_the_node_lights_up_under_the_mouse(self):
        self.move_mouse(1, BuildModel.PATH_COLUMN)
        self.assertEqual(1, self.table.hover_row)
        # The break and skip boxes beside it are not the node.
        for column in (BuildModel.BREAK_COLUMN, BuildModel.SKIP_COLUMN):
            self.move_mouse(1, column)
            self.assertEqual(-1, self.table.hover_row)


if __name__ == '__main__':
    unittest.main()
