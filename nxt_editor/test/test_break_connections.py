"""Breaking connections from the graph, with a right click.

A right click on a line, a point on it, or a plug offers to break the
connection. What the line came from is taken out of where it went and
nothing is left in its place: an exec input is cleared, and an attribute
loses the reference and is left empty when that was all it held.
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
from nxt import DATA_STATE
from nxt_editor import stage_model, wires

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

BASE = {
    'version': '1.17', 'alias': 'base',
    'nodes': {
        # Connections the top layer did not make.
        '/below': {'execute_in': '/first'},
        '/source': {},
        '/copy': {'instance': '/source'},
    },
}
TOP = {
    'version': '1.17', 'alias': 'top', 'references': ['./base.nxt'],
    'nodes': {
        '/first': {'attrs': {'value': {'type': 'raw', 'value': '5'}}},
        '/second': {'execute_in': '/first'},
        '/user': {'attrs': {
            'plain': {'type': 'raw', 'value': '${/first.value}'},
            'mixed': {'type': 'raw', 'value': 'a ${/first.value} b'},
        }},
    },
    'meta_data': {
        'positions': {'/first': [0.0, 0.0], '/second': [800.0, 0.0],
                      '/user': [800.0, 400.0], '/below': [800.0, -400.0]},
        'connection_points': {
            '/first>/second._execute_in': [[400.0, -100.0]]},
    },
}
EXEC = ('/first', '/second._execute_in')
PLAIN = ('/first.value', '/user.plain')
MIXED = ('/first.value', '/user.mixed')
BELOW = ('/first', '/below._execute_in')
COPY = ('/source', '/copy._instance')


class BreakCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_break_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, data in (('base.nxt', BASE), ('top.nxt', TOP)):
            with open(os.path.join(self.tmp, name), 'w') as fp:
                json.dump(data, fp)
        self.win = MainWindow(filepath=os.path.join(self.tmp, 'top.nxt'))
        self.win.resize(1400, 900)
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        # At 100%, where plugs are drawn: the graph is framed when it
        # opens, which can be zoomed out past where they are.
        self.view.resetTransform()
        self.view.centerOn(0, 0)
        self.model.set_attr_display_state(['/first', '/user'], 3)
        app.processEvents()

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def raw(self, node_path, attr):
        return self.model.get_node_attr_value(node_path, attr,
                                              self.model.comp_layer,
                                              data_state=DATA_STATE.RAW)

    def line(self, src, tgt):
        for line in self.view._connection_graphics:
            if (line.src_path, line.tgt_path) == (src, tgt):
                return line
        return None


class Breaking(BreakCase):

    def test_an_exec_line_leaves_no_exec_input(self):
        self.assertEqual(1, self.model.break_connections([EXEC]))
        app.processEvents()
        self.assertFalse(self.model.get_node_exec_in(
            '/second', self.model.comp_layer))
        self.assertIsNone(self.line(*EXEC))

    def test_it_takes_the_lines_points_too(self):
        self.model.break_connections([EXEC])
        self.assertEqual([], self.model.get_line_points(
            wires.line_key(*EXEC)))

    def test_an_attribute_is_left_empty_not_with_the_value(self):
        self.model.break_connections([PLAIN])
        app.processEvents()
        self.assertIn(self.raw('/user', 'plain'), (None, ''))
        resolved = self.model.get_node_attr_value('/user', 'plain',
                                                  self.model.comp_layer)
        self.assertNotEqual('5', resolved)
        self.assertIsNone(self.line(*PLAIN))

    def test_other_text_in_an_attribute_is_kept(self):
        self.model.break_connections([MIXED])
        self.assertEqual('a  b', self.raw('/user', 'mixed'))

    def test_a_weaker_layers_connection_is_broken_on_that_layer(self):
        # nxt reads an empty exec input as no opinion, so the top layer
        # cannot clear one the base layer made. It is left alone...
        self.assertEqual(0, self.model.break_connections([BELOW]))
        self.assertEqual('/first', self.model.get_node_exec_in(
            '/below', self.model.comp_layer))
        # ...until the layer that made it is the target.
        base = self.model.stage._sub_layers[1]
        self.model.set_target_layer(base.real_path)
        self.assertEqual(1, self.model.break_connections([BELOW]))
        app.processEvents()
        self.assertFalse(self.model.get_node_exec_in(
            '/below', self.model.comp_layer))

    def test_a_weaker_layers_instance_is_removed_from_the_top(self):
        # An empty instance path is an opinion, so unlike an exec input
        # an instance is removed whichever layer made it.
        self.assertEqual(1, self.model.break_connections([COPY]))
        app.processEvents()
        self.assertFalse(self.model.get_node_instance_path(
            '/copy', self.model.comp_layer))
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual('/source', self.model.get_node_instance_path(
            '/copy', self.model.comp_layer))

    def test_an_instance_made_here_leaves_no_empty_value(self):
        self.model.set_node_instance('/second', '/first')
        self.assertEqual(1, self.model.break_connections(
            [('/first', '/second._instance')]))
        node = self.model.target_layer.lookup('/second')
        self.assertIsNone(getattr(node, '_instance', None))
        self.assertFalse(self.model.get_node_instance_path(
            '/second', self.model.comp_layer))

    def test_breaking_several_is_one_undo(self):
        count = self.model.undo_stack.count()
        self.assertEqual(2, self.model.break_connections([EXEC, PLAIN]))
        self.assertEqual(count + 1, self.model.undo_stack.count())
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual('/first', self.model.get_node_exec_in(
            '/second', self.model.comp_layer))
        self.assertEqual('${/first.value}', self.raw('/user', 'plain'))
        self.assertEqual([[400.0, -100.0]], self.model.get_line_points(
            wires.line_key(*EXEC)))

    def test_a_reference_in_code_is_not_broken_here(self):
        self.assertEqual(0, self.model.break_connections(
            [('/first.value', '/user._code')]))


class RightClick(BreakCase):

    def view_pos(self, scene_pos):
        return self.view.mapFromScene(QtCore.QPointF(*scene_pos))

    def test_a_click_on_a_line_finds_it(self):
        exec_line = self.line(*EXEC)
        middle = exec_line.path().pointAtPercent(0.25)
        found = self.view.lines_at(self.view.mapFromScene(middle))
        self.assertEqual([EXEC], [(l.src_path, l.tgt_path) for l in found])

    def test_a_click_on_a_point_finds_its_line(self):
        found = self.view.lines_at(self.view_pos((400.0, -100.0)))
        self.assertEqual([EXEC], [(l.src_path, l.tgt_path) for l in found])

    def test_a_click_on_a_plug_finds_every_line_on_it(self):
        node = self.view.get_node_graphic('/first')
        out_plug = node._attr_plug_graphics['value']['out_plug']
        found = self.view.lines_at(self.view.mapFromScene(
            out_plug.scenePos()))
        self.assertEqual(sorted([PLAIN, MIXED]),
                         sorted((l.src_path, l.tgt_path) for l in found))

    def test_open_space_finds_nothing(self):
        self.assertEqual([], self.view.lines_at(
            self.view_pos((-3000.0, -3000.0))))


class ShowingAttributes(BreakCase):

    def line(self):
        return [line for line in self.view._connection_graphics
                if (line.src_path, line.tgt_path) == PLAIN][0]

    def test_a_line_moves_to_the_plug_its_node_shows(self):
        first = self.view.get_node_graphic('/first')
        self.model.set_attr_display_state(['/first'], 0)
        app.processEvents()
        self.assertEqual(first.get_attr_out_pos('_execute_in'),
                         self.line().src_pos)
        # Shown again, the line starts at the attribute, without the node
        # having to move first.
        self.model.set_attr_display_state(['/first'], 3)
        app.processEvents()
        self.assertEqual(first.get_attr_out_pos('value'),
                         self.line().src_pos)

    def test_a_line_moves_off_a_plug_its_target_hides(self):
        user = self.view.get_node_graphic('/user')
        self.assertEqual(user.get_attr_in_pos('plain'), self.line().tgt_pos)
        self.model.set_attr_display_state(['/user'], 0)
        app.processEvents()
        self.assertEqual(user.get_attr_in_pos('_execute_in'),
                         self.line().tgt_pos)


if __name__ == '__main__':
    unittest.main()
