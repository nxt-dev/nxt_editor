"""The Property Editor's position fields.

They follow a node while it is dragged, rather than only once it is let
go, and nothing goes on the undo stack until it is.

With several nodes selected they move all of them: a typed value puts
every one of them there on that axis, and a step of the arrows, the arrow
keys or the wheel moves every one of them by that much. Either is one
undo.
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
from Qt.QtTest import QTest

# Internal
from nxt_editor import stage_model
from nxt_editor.dockwidgets.property_editor import PropertyEditor
from nxt_editor.node_graphics_item import NodeGraphicsItem

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'positions', 'color': '#0052aa',
         'meta_data': {'positions': {'/a': [0.0, 0.0],
                                     '/b': [200.0, 50.0]}},
         'nodes': {'/a': {}, '/b': {}, '/a/child': {}}}


class PositionFieldsBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_positions_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'positions.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.editor = self.win.findChild(PropertyEditor)

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def select(self, *node_paths):
        self.model.set_selection(list(node_paths))
        app.processEvents()

    def fields(self):
        return (self.editor.positionX_field.value(),
                self.editor.positionY_field.value())


class FieldsFollowADrag(PositionFieldsBase):

    def item(self, node_path):
        for item in self.win.view.scene().items():
            if (isinstance(item, NodeGraphicsItem) and
                    item.node_path == node_path):
                return item
        self.fail('no graphic for ' + node_path)

    def test_fields_update_while_the_node_moves(self):
        self.select('/a')
        self.assertEqual(self.fields(), (0, 0))
        undo_count = self.model.undo_stack.count()
        # What a drag does to the graphic on each mouse move.
        item = self.item('/a')
        item.setPos(37, 12)
        app.processEvents()
        self.assertEqual(self.fields(), (37, 12),
                         'the fields waited for the drag to end')
        item.setPos(81, -40)
        app.processEvents()
        self.assertEqual(self.fields(), (81, -40))
        self.assertEqual(self.model.undo_stack.count(), undo_count,
                         'following a drag must not add undo steps')
        self.assertEqual(self.model.get_node_pos('/a'), [0.0, 0.0],
                         'nothing is set on a layer until the drag ends')

    def test_another_node_moving_leaves_the_fields_alone(self):
        self.select('/a')
        self.item('/b').setPos(500, 500)
        app.processEvents()
        self.assertEqual(self.fields(), (0, 0))


class FieldsMoveEverySelectedNode(PositionFieldsBase):

    def type_into(self, field, text):
        line_edit = field.lineEdit()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, text)
        QTest.keyClick(line_edit, QtCore.Qt.Key_Return)
        app.processEvents()

    def test_a_typed_x_sets_every_selected_node(self):
        self.select('/a', '/b')
        undo_count = self.model.undo_stack.count()
        self.type_into(self.editor.positionX_field, '120')
        self.assertEqual(self.model.get_node_pos('/a'), [120, 0.0])
        self.assertEqual(self.model.get_node_pos('/b'), [120, 50.0],
                         'the other selected node kept its x')
        self.assertEqual(self.model.undo_stack.count(), undo_count + 1,
                         'setting both should be one undo')
        self.model.undo()
        self.assertEqual(self.model.get_node_pos('/a'), [0.0, 0.0])
        self.assertEqual(self.model.get_node_pos('/b'), [200.0, 50.0])

    def test_a_typed_y_sets_every_selected_node(self):
        self.select('/a', '/b')
        self.type_into(self.editor.positionY_field, '-30')
        self.assertEqual(self.model.get_node_pos('/a'), [0.0, -30])
        self.assertEqual(self.model.get_node_pos('/b'), [200.0, -30])

    def test_a_step_offsets_every_selected_node(self):
        self.select('/a', '/b')
        undo_count = self.model.undo_stack.count()
        self.editor.positionX_field.stepBy(5)
        app.processEvents()
        self.assertEqual(self.model.get_node_pos('/a'), [5.0, 0.0])
        self.assertEqual(self.model.get_node_pos('/b'), [205.0, 50.0],
                         'a step moves every node by the same amount')
        self.assertEqual(self.model.undo_stack.count(), undo_count + 1)
        self.editor.positionY_field.stepBy(-3)
        app.processEvents()
        self.assertEqual(self.model.get_node_pos('/a'), [5.0, -3.0])
        self.assertEqual(self.model.get_node_pos('/b'), [205.0, 47.0])
        self.model.undo()
        self.model.undo()
        self.assertEqual(self.model.get_node_pos('/b'), [200.0, 50.0])

    def test_child_nodes_in_the_selection_are_left_alone(self):
        self.select('/a', '/a/child')
        self.type_into(self.editor.positionX_field, '40')
        self.assertEqual(self.model.get_node_pos('/a'), [40, 0.0])
        self.assertNotIn('/a/child', self.model.comp_layer.positions)

    def test_leaving_an_untouched_field_moves_nothing(self):
        self.select('/a', '/b')
        undo_count = self.model.undo_stack.count()
        self.editor.positionX_field.editingFinished.emit()
        app.processEvents()
        self.assertEqual(self.model.undo_stack.count(), undo_count)
        self.assertEqual(self.model.get_node_pos('/b'), [200.0, 50.0])


if __name__ == '__main__':
    unittest.main()
