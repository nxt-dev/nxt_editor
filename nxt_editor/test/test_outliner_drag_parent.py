"""Dragging rows in the Outliner onto another row parents their nodes to
it, and dragging them off the rows unparents them, as one undo."""
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
from nxt import nxt_path
from nxt_editor import stage_model
from nxt_editor.dockwidgets.outliner import NODE_PATHS_MIME

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {
    'version': '1.17', 'alias': 'drag',
    'nodes': {'/a': {}, '/b': {}, '/c': {}, '/c/kid': {}, '/c/kid/deep': {}},
    'meta_data': {'positions': {'/a': [0.0, 0.0], '/b': [300.0, 0.0],
                                '/c': [600.0, 0.0]}},
}


class DragToParent(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_drag_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'drag.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.win.view.ensure_drawn()
        self.outliner = self.win.outliner
        self.outliner.show()
        # Floating, tall enough to have room below the rows whatever the
        # docked layout.
        self.outliner.setFloating(True)
        self.outliner.resize(300, 600)
        app.processEvents()
        self.tree = self.outliner.tree
        self.rebuild()

    def tearDown(self):
        self.outliner.setFloating(False)
        self.outliner.hide()
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def rebuild(self):
        app.processEvents()
        self.outliner.rebuild_timer.stop()
        self.outliner.rebuild()
        app.processEvents()

    def row_pos(self, path):
        item = self.outliner.items[path]
        self.tree.scrollToItem(item)
        return self.tree.visualItemRect(item).center()

    def empty_pos(self):
        """Somewhere below the rows."""
        rect = self.tree.viewport().rect()
        for y in range(rect.bottom() - 2, 0, -4):
            pos = QtCore.QPoint(rect.center().x(), y)
            if self.tree.itemAt(pos) is None:
                return pos
        self.fail('no room below the rows: {}'.format(rect))

    def drop(self, paths, pos):
        mime = QtCore.QMimeData()
        mime.setData(NODE_PATHS_MIME, json.dumps(paths).encode('utf-8'))
        event = QtGui.QDropEvent(QtCore.QPointF(pos), QtCore.Qt.MoveAction,
                                 mime, QtCore.Qt.LeftButton,
                                 QtCore.Qt.NoModifier)
        self.tree.dropEvent(event)
        app.processEvents()
        self.rebuild()
        return event.isAccepted()

    def move(self, paths, pos):
        """Where a drag over pos would drop, as the tree shows it."""
        mime = QtCore.QMimeData()
        mime.setData(NODE_PATHS_MIME, json.dumps(paths).encode('utf-8'))
        event = QtGui.QDragMoveEvent(QtCore.QPoint(pos), QtCore.Qt.MoveAction,
                                     mime, QtCore.Qt.LeftButton,
                                     QtCore.Qt.NoModifier)
        self.tree.dragMoveEvent(event)
        return event.isAccepted(), self.tree.drop_target

    def test_dropping_rows_on_a_row_parents_them_in_one_undo(self):
        before = self.model.undo_stack.count()
        self.assertTrue(self.drop(['/a', '/b'], self.row_pos('/c')))
        self.assertTrue(self.model.node_exists('/c/a'))
        self.assertTrue(self.model.node_exists('/c/b'))
        self.assertFalse(self.model.node_exists('/a'))
        self.assertEqual(before + 1, self.model.undo_stack.count())
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertTrue(self.model.node_exists('/a'))
        self.assertFalse(self.model.node_exists('/c/a'))

    def test_dropping_off_the_rows_unparents(self):
        self.assertTrue(self.drop(['/c/kid'], self.empty_pos()))
        self.assertTrue(self.model.node_exists('/kid'))
        self.assertTrue(self.model.node_exists('/kid/deep'))
        self.assertFalse(self.model.node_exists('/c/kid'))

    def test_dropping_on_a_group_heading_unparents(self):
        heading = self.outliner.sections['']
        pos = self.tree.visualItemRect(heading).center()
        self.assertTrue(self.drop(['/c/kid'], pos))
        self.assertTrue(self.model.node_exists('/kid'))

    def test_a_node_cannot_go_under_itself_or_below_it(self):
        before = self.model.undo_stack.count()
        self.assertFalse(self.drop(['/c'], self.row_pos('/c')))
        self.assertFalse(self.drop(['/c'], self.row_pos('/c/kid/deep')))
        self.assertEqual(before, self.model.undo_stack.count())
        self.assertTrue(self.model.node_exists('/c/kid/deep'))

    def test_where_it_already_is_is_refused(self):
        accepted, target = self.move(['/c/kid'], self.row_pos('/c'))
        self.assertFalse(accepted)
        self.assertIsNone(target)

    def test_the_row_it_would_go_under_is_marked(self):
        accepted, target = self.move(['/a'], self.row_pos('/c'))
        self.assertTrue(accepted)
        self.assertEqual('/c', target)
        accepted, target = self.move(['/c/kid'], self.empty_pos())
        self.assertTrue(accepted)
        self.assertEqual(nxt_path.WORLD, target)
        accepted, target = self.move(['/c'], self.row_pos('/c/kid'))
        self.assertFalse(accepted)
        self.assertIsNone(target)

    def test_a_drag_takes_the_top_most_selected_nodes(self):
        self.model.set_selection(['/c', '/c/kid', '/a'])
        app.processEvents()
        self.assertEqual(sorted(['/c', '/a']),
                         sorted(self.tree.dragged_paths()))

    def test_rows_can_be_dragged_and_headings_cannot(self):
        item = self.outliner.items['/a']
        self.assertTrue(item.flags() & QtCore.Qt.ItemIsDragEnabled)
        heading = self.outliner.sections['']
        self.assertFalse(heading.flags() & QtCore.Qt.ItemIsDragEnabled)


if __name__ == '__main__':
    unittest.main()
