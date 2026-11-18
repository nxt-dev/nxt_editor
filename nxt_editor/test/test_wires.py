"""Lines between nodes: straight or curved, and the points they pass through.

The style belongs to the graph and the points to one line each. Both are
saved in the top layer's meta data, like backdrops, and a lower layer's
are shown until the top layer says otherwise.
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
from nxt.session import Session
from nxt_editor import connection_graphics_item, stage_model, user_dir, wires

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

EXEC_KEY = '/first>/second._execute_in'
LOWER_KEY = '/old>/gone._execute_in'
BASE = {
    'version': '1.17', 'alias': 'base',
    'nodes': {},
    'meta_data': {'connection_style': 'curved',
                  'connection_points': {LOWER_KEY: [[5.0, 5.0]]}},
}
TOP = {
    'version': '1.17', 'alias': 'top', 'references': ['./base.nxt'],
    'nodes': {'/first': {}, '/second': {'execute_in': '/first'}},
    'meta_data': {'positions': {'/first': [0.0, 0.0],
                                '/second': [800.0, 400.0]}},
}


def write_graph(tmp, base=None, top=None):
    for name, data in (('base.nxt', base or BASE), ('top.nxt', top or TOP)):
        with open(os.path.join(tmp, name), 'w') as fp:
            json.dump(data, fp)
    return os.path.join(tmp, 'top.nxt')


def without_style_preference(case):
    """Run a test with no connection style preference, putting back the
    user's own afterwards: these are real preferences on disk."""
    key = user_dir.USER_PREF.CONNECTION_STYLE
    had = key in user_dir.user_prefs
    saved = user_dir.user_prefs.get(key)

    def restore():
        if had:
            user_dir.user_prefs[key] = saved
        elif key in user_dir.user_prefs:
            user_dir.user_prefs.pop(key)
    case.addCleanup(restore)
    if had:
        user_dir.user_prefs.pop(key)


def saved_meta(path):
    with open(path) as fp:
        return json.load(fp).get('meta_data', {})


class Helpers(unittest.TestCase):

    def test_points_are_cleaned(self):
        self.assertEqual([[1.0, 2.0]],
                         wires.clean_points([[1, 2], 'junk', [3]]))
        self.assertIsNone(wires.clean_points('junk'))

    def test_a_new_point_goes_in_the_nearest_piece(self):
        points = [[100.0, 0.0], [100.0, 100.0]]
        self.assertEqual(0, wires.insert_index((0, 0), points, (200, 100),
                                               (50, 2)))
        self.assertEqual(1, wires.insert_index((0, 0), points, (200, 100),
                                               (98, 50)))
        self.assertEqual(2, wires.insert_index((0, 0), points, (200, 100),
                                               (150, 101)))


class ModelCase(unittest.TestCase):

    def setUp(self):
        without_style_preference(self)
        self.tmp = tempfile.mkdtemp(prefix='nxt_wires_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = write_graph(self.tmp)
        self.model = self.load()
        self.changed = []
        self.model.wires_changed.connect(lambda: self.changed.append(True))

    def load(self):
        return stage_model.StageModel(Session().load_file(filepath=self.path))


class StyleTests(ModelCase):

    def test_a_lower_layers_style_is_used(self):
        self.assertEqual(wires.CURVED, self.model.get_connection_style())

    def test_a_graph_with_none_is_straight(self):
        path = write_graph(self.tmp, base=dict(BASE, meta_data={}))
        model = stage_model.StageModel(Session().load_file(filepath=path))
        self.assertEqual(wires.STRAIGHT, model.get_connection_style())

    def test_changing_it_is_one_undo_saved_on_the_top_layer(self):
        self.model.set_connection_style(wires.STRAIGHT)
        self.assertEqual(wires.STRAIGHT, self.model.get_connection_style())
        self.assertTrue(self.changed)
        self.model.top_layer.save()
        self.assertEqual('straight', saved_meta(self.path)[wires.STYLE_KEY])
        self.assertEqual(wires.STRAIGHT, self.load().get_connection_style())
        self.model.undo_stack.undo()
        self.assertEqual(wires.CURVED, self.model.get_connection_style())

    def test_matching_the_lower_layer_leaves_no_key_behind(self):
        self.model.set_connection_style(wires.STRAIGHT)
        self.model.set_connection_style(wires.CURVED)
        self.model.top_layer.save()
        self.assertNotIn(wires.STYLE_KEY, saved_meta(self.path))

    def test_nonsense_is_ignored(self):
        self.model.set_connection_style('wiggly')
        self.assertFalse(self.changed)
        self.assertNotIn(user_dir.USER_PREF.CONNECTION_STYLE,
                         user_dir.user_prefs)

    def test_changing_it_is_remembered_as_the_preference(self):
        self.model.set_connection_style(wires.STRAIGHT)
        self.assertEqual(wires.STRAIGHT, user_dir.user_prefs.get(
            user_dir.USER_PREF.CONNECTION_STYLE))

    def test_undo_puts_the_preference_back(self):
        key = user_dir.USER_PREF.CONNECTION_STYLE
        self.model.set_connection_style(wires.STRAIGHT)
        self.model.undo_stack.undo()
        self.assertNotIn(key, user_dir.user_prefs)
        self.model.undo_stack.redo()
        self.assertEqual(wires.STRAIGHT, user_dir.user_prefs.get(key))

    def test_a_graph_with_none_follows_the_preference(self):
        path = write_graph(self.tmp, base=dict(BASE, meta_data={}))
        model = stage_model.StageModel(Session().load_file(filepath=path))
        key = user_dir.USER_PREF.CONNECTION_STYLE
        user_dir.user_prefs[key] = wires.CURVED
        self.assertEqual(wires.CURVED, model.get_connection_style())

    def test_a_graph_that_saves_one_keeps_it_over_the_preference(self):
        key = user_dir.USER_PREF.CONNECTION_STYLE
        user_dir.user_prefs[key] = wires.STRAIGHT
        # The base layer saves curved.
        self.assertEqual(wires.CURVED, self.model.get_connection_style())


class PointTests(ModelCase):

    def test_a_lower_layers_points_are_shown(self):
        self.assertEqual([[5.0, 5.0]], self.model.get_line_points(LOWER_KEY))

    def test_setting_points_is_one_undo_saved_on_the_top_layer(self):
        self.model.set_line_points(EXEC_KEY, [[10, 20], [30, 40]])
        self.assertEqual([[10.0, 20.0], [30.0, 40.0]],
                         self.model.get_line_points(EXEC_KEY))
        self.model.top_layer.save()
        meta = saved_meta(self.path)
        self.assertEqual([[10.0, 20.0], [30.0, 40.0]],
                         meta[wires.POINTS_KEY][EXEC_KEY])
        self.assertNotIn(LOWER_KEY, meta[wires.POINTS_KEY])
        self.assertEqual([[10.0, 20.0], [30.0, 40.0]],
                         self.load().get_line_points(EXEC_KEY))
        self.model.undo_stack.undo()
        self.assertEqual([], self.model.get_line_points(EXEC_KEY))

    def test_removing_the_last_point_leaves_no_key_behind(self):
        self.model.set_line_points(EXEC_KEY, [[10, 20]])
        self.model.set_line_points(EXEC_KEY, [])
        self.model.top_layer.save()
        self.assertNotIn(wires.POINTS_KEY, saved_meta(self.path))

    def test_removing_a_lower_layers_points_hides_them(self):
        self.model.set_line_points(LOWER_KEY, [])
        self.assertEqual([], self.model.get_line_points(LOWER_KEY))
        self.model.top_layer.save()
        self.assertIsNone(saved_meta(self.path)[wires.POINTS_KEY][LOWER_KEY])

    def test_hand_edited_junk_does_not_break_the_graph(self):
        top = dict(TOP, meta_data={wires.STYLE_KEY: 7,
                                   wires.POINTS_KEY: {EXEC_KEY: 'x',
                                                      'a>b': [[1, 'y']]}})
        path = write_graph(self.tmp, top=top)
        model = stage_model.StageModel(Session().load_file(filepath=path))
        self.assertEqual(wires.CURVED, model.get_connection_style())
        self.assertEqual({LOWER_KEY: [[5.0, 5.0]]}, model.get_line_points())



class InstanceArrow(unittest.TestCase):

    def test_the_line_stops_where_the_arrow_starts(self):
        anchors = [QtCore.QPointF(0, 0), QtCore.QPointF(200, 0)]
        path, arrow = connection_graphics_item.arrow_line(anchors, False)
        tip = 200 - connection_graphics_item.ARROW_GAP
        base = tip - connection_graphics_item.ARROW_LENGTH
        self.assertEqual(QtCore.QPointF(tip, 0), arrow[0])
        self.assertAlmostEqual(base, path.currentPosition().x())

    def test_a_curved_line_arrives_going_right(self):
        anchors = [QtCore.QPointF(0, 0), QtCore.QPointF(-100, 300)]
        path, arrow = connection_graphics_item.arrow_line(anchors, True)
        self.assertAlmostEqual(arrow[0].y(), 300)
        self.assertAlmostEqual(arrow[1].x(), arrow[2].x())
        self.assertLess(arrow[1].x(), arrow[0].x())

    def test_zoomed_out_the_arrow_is_twice_as_long(self):
        anchors = [QtCore.QPointF(0, 0), QtCore.QPointF(200, 0)]
        _, arrow = connection_graphics_item.arrow_line(anchors, False,
                                                        scale=2.0)
        self.assertAlmostEqual(arrow[0].x() - arrow[1].x(),
                               connection_graphics_item.ARROW_LENGTH * 2)

class PointDirection(unittest.TestCase):
    """A curved line passes through a point the way it goes from the
    anchor before it to the one after."""

    def direction(self, previous_x, current=None):
        return connection_graphics_item.point_direction(
            QtCore.QPointF(previous_x, 0), QtCore.QPointF(0, 0), current)

    def test_going_on_to_the_right_it_goes_right(self):
        self.assertEqual(connection_graphics_item.RIGHT, self.direction(-50))

    def test_going_on_to_the_left_it_goes_left(self):
        self.assertEqual(connection_graphics_item.LEFT, self.direction(50))

    def test_it_only_turns_round_past_the_margin(self):
        margin = connection_graphics_item.TURN_MARGIN
        right, left = connection_graphics_item.RIGHT, \
            connection_graphics_item.LEFT
        self.assertEqual(right, self.direction(margin - 1, right))
        self.assertEqual(left, self.direction(margin + 1, right))
        self.assertEqual(left, self.direction(1 - margin, left))
        self.assertEqual(right, self.direction(-margin - 1, left))

    def test_without_directions_every_piece_goes_right(self):
        anchors = [QtCore.QPointF(0, 0), QtCore.QPointF(100, 0)]
        path = connection_graphics_item.line_path(anchors, True)
        self.assertEqual(50.0, path.elementAt(1).x)
        self.assertEqual(50.0, path.elementAt(2).x)


class ViewCase(unittest.TestCase):

    def setUp(self):
        without_style_preference(self)
        self.tmp = tempfile.mkdtemp(prefix='nxt_wires_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        base = dict(BASE, meta_data={})
        self.path = write_graph(self.tmp, base=base)
        self.win = MainWindow(filepath=self.path)
        self.win.resize(1400, 900)
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        self.view.resetTransform()
        self.view.centerOn(400, 200)
        app.processEvents()

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    @property
    def line(self):
        for graphic in self.view.get_node_connection_graphics('/second'):
            if graphic.key == EXEC_KEY:
                return graphic
        self.fail('No exec line drawn')

    def middle(self):
        line = self.line
        return ((line.src_pos.x() + line.tgt_pos.x()) / 2,
                (line.src_pos.y() + line.tgt_pos.y()) / 2)

    def event(self, kind, scene_pos, button=QtCore.Qt.LeftButton,
              modifiers=QtCore.Qt.NoModifier):
        local = QtCore.QPointF(self.view.mapFromScene(QtCore.QPointF(
            *scene_pos)))
        held = button if kind != QtCore.QEvent.MouseButtonRelease \
            else QtCore.Qt.NoButton
        if kind == QtCore.QEvent.MouseMove:
            button = QtCore.Qt.NoButton
            held = QtCore.Qt.LeftButton
        return QtGui.QMouseEvent(kind, local, self.view.mapToGlobal(local),
                                 button, held, modifiers)

    def mouse(self, kind, scene_pos, modifiers=QtCore.Qt.NoModifier):
        handler = {
            QtCore.QEvent.MouseButtonPress: self.view.mousePressEvent,
            QtCore.QEvent.MouseMove: self.view.mouseMoveEvent,
            QtCore.QEvent.MouseButtonRelease: self.view.mouseReleaseEvent,
            QtCore.QEvent.MouseButtonDblClick:
                self.view.mouseDoubleClickEvent}[kind]
        handler(self.event(kind, scene_pos, modifiers=modifiers))
        app.processEvents()

    def double_click(self, scene_pos):
        self.mouse(QtCore.QEvent.MouseButtonDblClick, scene_pos)

    def click(self, scene_pos, modifiers=QtCore.Qt.NoModifier):
        self.mouse(QtCore.QEvent.MouseButtonPress, scene_pos, modifiers)
        self.mouse(QtCore.QEvent.MouseButtonRelease, scene_pos, modifiers)

    def drag(self, start, end):
        self.mouse(QtCore.QEvent.MouseButtonPress, start)
        mid = ((start[0] + end[0]) * .5, (start[1] + end[1]) * .5)
        self.mouse(QtCore.QEvent.MouseMove, mid)
        self.mouse(QtCore.QEvent.MouseMove, end)
        self.mouse(QtCore.QEvent.MouseButtonRelease, end)

    def path_points(self):
        path = self.line.path()
        return [(path.elementAt(i).x, path.elementAt(i).y)
                for i in range(path.elementCount())]


class LinesInTheView(ViewCase):

    def test_lines_start_straight(self):
        self.assertFalse(self.win.view_actions.curved_action.isChecked())
        self.assertEqual(2, self.line.path().elementCount())

    def test_the_view_menu_curves_this_graphs_lines(self):
        action = self.win.view_actions.curved_action
        action.trigger()
        app.processEvents()
        self.assertEqual(wires.CURVED, self.model.get_connection_style())
        # A cubic is the end point and its two pulls.
        self.assertEqual(4, self.line.path().elementCount())
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual(2, self.line.path().elementCount())
        self.assertFalse(action.isChecked())

    def test_double_clicking_a_line_adds_a_point_there(self):
        middle = self.middle()
        self.double_click(middle)
        points = self.model.get_line_points(EXEC_KEY)
        self.assertEqual(1, len(points))
        self.assertAlmostEqual(middle[0], points[0][0], delta=1)
        self.assertAlmostEqual(middle[1], points[0][1], delta=1)
        self.assertEqual(1, len(self.line.point_graphics))
        # The line now bends through it.
        self.assertAlmostEqual(points[0][0], self.path_points()[1][0])
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([], self.line.point_graphics)

    def test_double_clicking_near_a_line_still_lands_on_it(self):
        x, y = self.middle()
        self.double_click((x, y + 3))
        self.assertEqual(1, len(self.model.get_line_points(EXEC_KEY)))

    def test_double_clicking_open_space_adds_nothing(self):
        self.double_click((-2000, -2000))
        self.assertEqual({}, self.model.get_line_points())

    def test_dragging_a_point_moves_it_in_one_undo(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        count = self.model.undo_stack.count()
        self.drag((400, 0), (420, 300))
        self.assertEqual(count + 1, self.model.undo_stack.count())
        point = self.model.get_line_points(EXEC_KEY)[0]
        self.assertAlmostEqual(420, point[0], delta=10)
        self.assertAlmostEqual(300, point[1], delta=10)
        self.assertEqual(['/first', '/second'],
                         sorted(self.view._node_graphics))
        self.assertEqual([], self.model.get_selected_nodes())

    def test_dragging_one_selected_point_moves_them_all(self):
        self.model.add_node(name='third', pos=[1600.0, 0.0])
        self.model.set_node_exec_in('/third', '/second')
        other_key = '/second>/third._execute_in'
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        self.model.set_line_points(other_key, [[1200.0, 200.0]])
        app.processEvents()
        self.click((400, 0))
        self.click((400, 300), self.view.SEL_TOGGLE_MODIFIERS)
        self.click((1200, 200), self.view.SEL_TOGGLE_MODIFIERS)
        self.assertEqual(3, len(self.view.selected_points))
        count = self.model.undo_stack.count()
        self.drag((400, 0), (450, 100))
        self.assertEqual(count + 1, self.model.undo_stack.count())
        moved = self.model.get_line_points(EXEC_KEY) + \
            self.model.get_line_points(other_key)
        for (x, y), (start_x, start_y) in zip(
                moved, [(400, 0), (400, 300), (1200, 200)]):
            self.assertAlmostEqual(start_x + 50, x, delta=10)
            self.assertAlmostEqual(start_y + 100, y, delta=10)
        # They stay selected, and one undo puts them all back.
        self.assertEqual(3, len(self.view.selected_points))
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([[400.0, 0.0], [400.0, 300.0]],
                         self.model.get_line_points(EXEC_KEY))
        self.assertEqual([[1200.0, 200.0]],
                         self.model.get_line_points(other_key))

    def test_dragging_an_unselected_point_moves_only_it(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        app.processEvents()
        self.click((400, 300))
        self.drag((400, 0), (450, 100))
        points = self.model.get_line_points(EXEC_KEY)
        self.assertAlmostEqual(450, points[0][0], delta=10)
        self.assertEqual([400.0, 300.0], points[1])

    def test_double_clicking_a_point_removes_it(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        app.processEvents()
        self.double_click((400, 0))
        self.assertEqual([[400.0, 300.0]],
                         self.model.get_line_points(EXEC_KEY))

    def test_delete_takes_the_selected_points_and_leaves_the_nodes(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        app.processEvents()
        self.click((400, 0))
        self.assertEqual([(EXEC_KEY, 0)], self.view.selected_points)
        self.win.node_actions.delete_node_action.trigger()
        app.processEvents()
        self.assertEqual([[400.0, 300.0]],
                         self.model.get_line_points(EXEC_KEY))
        self.assertIsNotNone(self.model.comp_layer.lookup('/first'))
        self.assertEqual([], self.view.selected_points)

    def box(self, start, end, modifiers=QtCore.Qt.NoModifier):
        """Drag a selection box from open space."""
        self.mouse(QtCore.QEvent.MouseButtonPress, start, modifiers)
        self.mouse(QtCore.QEvent.MouseMove, end, modifiers)
        self.mouse(QtCore.QEvent.MouseButtonRelease, end, modifiers)

    def test_a_box_selects_the_points_inside_it(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        app.processEvents()
        self.box((350, -60), (450, 320))
        self.assertEqual([(EXEC_KEY, 0), (EXEC_KEY, 1)],
                         self.view.selected_points)
        self.assertEqual([], self.model.get_selected_nodes())

    def test_a_box_starts_in_the_space_a_bent_line_goes_round(self):
        # Bent through a point, the line goes round a triangle of open
        # space, which a box can still be started in.
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        inside = QtCore.QPointF(487, 143)
        self.assertTrue(self.line.path().contains(inside))
        self.assertGreater(self.line.distance(inside), 20)
        self.box((487, 143), (350, -60))
        self.assertEqual([(EXEC_KEY, 0)], self.view.selected_points)

    def test_a_box_with_shift_toggles_points(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        app.processEvents()
        self.click((400, 0))
        self.box((350, -60), (450, 320), QtCore.Qt.ShiftModifier)
        self.assertEqual([(EXEC_KEY, 1)], self.view.selected_points)

    def test_delete_takes_the_points_and_nodes_a_box_picked_up(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0], [400.0, 300.0]])
        app.processEvents()
        self.box((-30, -30), (450, 60))
        self.assertEqual(['/first'], self.model.get_selected_nodes())
        self.assertEqual([(EXEC_KEY, 0)], self.view.selected_points)
        count = self.model.undo_stack.count()
        self.win.node_actions.delete_node_action.trigger()
        app.processEvents()
        self.assertIsNone(self.model.comp_layer.lookup('/first'))
        self.assertEqual([[400.0, 300.0]],
                         self.model.get_line_points(EXEC_KEY))
        self.assertEqual(count + 1, self.model.undo_stack.count())
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertIsNotNone(self.model.comp_layer.lookup('/first'))
        self.assertEqual([[400.0, 0.0], [400.0, 300.0]],
                         self.model.get_line_points(EXEC_KEY))

    def test_points_stay_the_same_size_on_screen_zoomed_out(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        graphic = self.line.point_graphics[0]
        size = graphic.boundingRect().width()
        for scale in (1.0, 0.1):
            self.view.resetTransform()
            self.view.scale(scale, scale)
            app.processEvents()
            on_screen = graphic.deviceTransform(
                self.view.viewportTransform()).mapRect(
                graphic.boundingRect())
            self.assertAlmostEqual(size, on_screen.width(), delta=0.5)

    def test_clicking_elsewhere_lets_go_of_a_point(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        self.click((400, 0))
        self.click((-2000, -2000))
        self.assertEqual([], self.view.selected_points)

    def test_points_stay_put_when_a_node_moves(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        self.model.set_nodes_pos({'/second': [900.0, 500.0]})
        app.processEvents()
        self.assertEqual((400.0, 0.0), self.path_points()[1])

    def curve_through_point(self):
        """The pull the line arrives at its one point with, the point, and
        the pull it leaves with, as x positions."""
        points = self.path_points()
        return points[2][0], points[3][0], points[4][0]

    def test_a_point_ahead_of_the_line_is_passed_going_right(self):
        self.win.view_actions.curved_action.trigger()
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        arrive, point, leave = self.curve_through_point()
        self.assertLess(arrive, point)
        self.assertGreater(leave, point)

    def test_a_point_behind_the_source_still_goes_toward_the_target(self):
        # The ends decide which way, not where the point is.
        self.win.view_actions.curved_action.trigger()
        self.model.set_line_points(EXEC_KEY, [[-300.0, 200.0]])
        app.processEvents()
        self.assertEqual(connection_graphics_item.RIGHT,
                         self.line.point_graphics[0].direction)

    def test_a_target_behind_the_source_is_reached_going_left(self):
        self.win.view_actions.curved_action.trigger()
        self.model.set_nodes_pos({'/second': [-800.0, 400.0]})
        self.model.set_line_points(EXEC_KEY, [[-300.0, 200.0]])
        app.processEvents()
        self.assertEqual(connection_graphics_item.LEFT,
                         self.line.point_graphics[0].direction)
        arrive, point, leave = self.curve_through_point()
        self.assertGreater(arrive, point)
        self.assertLess(leave, point)

    def test_a_point_turns_round_when_its_ends_cross(self):
        self.win.view_actions.curved_action.trigger()
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        graphic = self.line.point_graphics[0]
        self.assertEqual(connection_graphics_item.RIGHT, graphic.direction)
        self.model.set_nodes_pos({'/first': [1000.0, 0.0]})
        app.processEvents()
        self.assertEqual(connection_graphics_item.LEFT, graphic.direction)
        arrive, point, leave = self.curve_through_point()
        self.assertGreater(arrive, point)
        self.assertLess(leave, point)

    def test_a_new_line_is_drawn_through_its_saved_points(self):
        self.model.set_line_points(EXEC_KEY, [[400.0, 0.0]])
        app.processEvents()
        self.model.set_node_exec_in('/second', None)
        self.model.set_node_exec_in('/second', '/first')
        app.processEvents()
        self.assertEqual(1, len(self.line.point_graphics))


if __name__ == '__main__':
    unittest.main()
