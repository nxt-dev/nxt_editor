"""Backdrops: titled, colored boxes behind groups of nodes.

A backdrop is saved in the top layer's meta data and is never part of the
graph. Moving one moves the nodes inside it, as in Nuke, Natron and
Unreal, and the move is a single undo. What it holds is worked out from
where things are when it is grabbed, not saved, so nothing has to keep a
list of node paths up to date.
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
from nxt_editor import backdrops, stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402
from nxt_editor.backdrop_graphics_item import (  # noqa: E402
    BackdropGraphicsItem)

BASE = {
    'version': '1.17', 'alias': 'base',
    'nodes': {'/low': {}},
    'meta_data': {
        'positions': {'/low': [0.0, 600.0]},
        'backdrops': {
            'bd_low': {'pos': [-50.0, 500.0], 'size': [400.0, 300.0],
                       'title': 'From below', 'note': '',
                       'color': '#2f5578'}}},
}
TOP = {
    'version': '1.17', 'alias': 'top', 'references': ['./base.nxt'],
    'nodes': {'/inside': {}, '/inside/child': {}, '/outside': {}},
    'meta_data': {'positions': {'/inside': [0.0, 0.0],
                                '/outside': [1200.0, 0.0]}},
}


def write_graph(tmp):
    for name, data in (('base.nxt', BASE), ('top.nxt', TOP)):
        with open(os.path.join(tmp, name), 'w') as fp:
            json.dump(data, fp)
    return os.path.join(tmp, 'top.nxt')


def saved_meta(path):
    with open(path) as fp:
        return json.load(fp).get('meta_data', {})


class BackdropData(unittest.TestCase):
    """What the model keeps and what ends up in the file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_backdrops_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = write_graph(self.tmp)
        self.stage = Session().load_file(filepath=self.path)
        self.model = stage_model.StageModel(self.stage)
        self.changed = []
        self.model.backdrops_changed.connect(
            lambda: self.changed.append(True))

    def add(self, **fields):
        record = backdrops.make((-100, -100), (600, 400), **fields)
        return self.model.add_backdrop(record)

    def test_a_lower_layers_backdrop_is_shown(self):
        shown = self.model.get_backdrops()
        self.assertEqual(['bd_low'], list(shown))
        self.assertEqual('From below', shown['bd_low']['title'])

    def test_adding_one_is_one_undo(self):
        backdrop_id = self.add(title='Rig', note='Builds the rig.')
        self.assertTrue(self.changed)
        self.assertEqual('Builds the rig.',
                         self.model.get_backdrop(backdrop_id)['note'])
        self.assertEqual(1, self.model.undo_stack.count())
        self.model.undo_stack.undo()
        self.assertIsNone(self.model.get_backdrop(backdrop_id))
        self.model.undo_stack.redo()
        self.assertEqual('Rig', self.model.get_backdrop(backdrop_id)['title'])

    def test_it_is_saved_with_the_top_layer_and_opens_again(self):
        backdrop_id = self.add(title='Rig', note='Line one\nLine two',
                               color='#7a4428')
        self.assertIn(self.model.top_layer.real_path,
                      self.model.effected_layers)
        self.model.top_layer.save()
        meta = saved_meta(self.path)
        self.assertEqual(['Rig'], [r['title'] for r in
                                   meta['backdrops'].values()])
        # The lower layer's backdrop stays in the lower layer.
        self.assertNotIn('bd_low', meta['backdrops'])
        reopened = stage_model.StageModel(
            Session().load_file(filepath=self.path))
        record = reopened.get_backdrop(backdrop_id)
        self.assertEqual('Line one\nLine two', record['note'])
        self.assertEqual('#7a4428', record['color'])
        self.assertEqual([600.0, 400.0], record['size'])

    def test_removing_the_last_one_leaves_no_key_behind(self):
        backdrop_id = self.add()
        self.model.remove_backdrops([backdrop_id])
        self.model.top_layer.save()
        self.assertNotIn('backdrops', saved_meta(self.path))

    def test_editing_a_lower_layers_backdrop_writes_the_top_layer(self):
        self.model.edit_backdrop('bd_low', title='Renamed')
        self.assertEqual('Renamed', self.model.get_backdrop('bd_low')['title'])
        base = self.model.stage._sub_layers[1]
        self.assertEqual('From below',
                         backdrops.layer_backdrops(base)['bd_low']['title'])

    def test_deleting_a_lower_layers_backdrop_hides_it(self):
        self.model.remove_backdrops(['bd_low'])
        self.assertEqual({}, self.model.get_backdrops())
        self.assertIsNone(
            backdrops.layer_backdrops(self.model.top_layer)['bd_low'])
        self.model.undo_stack.undo()
        self.assertIn('bd_low', self.model.get_backdrops())
        self.assertNotIn('bd_low',
                         backdrops.layer_backdrops(self.model.top_layer))

    def test_hand_edited_junk_does_not_break_the_graph(self):
        self.model.top_layer._input_metadata['backdrops'] = {
            'bd_bad': {'pos': 'nowhere', 'size': [1], 'title': 5},
            'bd_worse': 'not a backdrop'}
        shown = self.model.get_backdrops()
        self.assertNotIn('bd_worse', shown)
        self.assertEqual([0.0, 0.0], shown['bd_bad']['pos'])
        self.assertEqual(backdrops.DEFAULT_TITLE, shown['bd_bad']['title'])
        self.assertEqual(list(backdrops.DEFAULT_SIZE), shown['bd_bad']['size'])

    def test_an_untitled_graph_takes_backdrops(self):
        model = stage_model.StageModel(Session().new_file())
        backdrop_id = model.add_backdrop(backdrops.make((0, 0)))
        self.assertIsNotNone(model.get_backdrop(backdrop_id))


class ViewCase(unittest.TestCase):
    """A window on the test graph, and a mouse to use in it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_backdrops_')
        self.path = write_graph(self.tmp)
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
        self.win = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers

    def add(self, pos=(-100, -100), size=(600, 400)):
        backdrop_id = self.model.add_backdrop(backdrops.make(pos, size))
        app.processEvents()
        return backdrop_id

    def node_pos(self, path):
        return list(self.model.get_node_pos(path))

    def mouse(self, kind, scene_pos, button=QtCore.Qt.LeftButton,
              modifiers=QtCore.Qt.NoModifier):
        local = QtCore.QPointF(self.view.mapFromScene(QtCore.QPointF(
            *scene_pos)))
        held = button if kind != QtCore.QEvent.MouseButtonRelease \
            else QtCore.Qt.NoButton
        if kind == QtCore.QEvent.MouseMove:
            button = QtCore.Qt.NoButton
            held = QtCore.Qt.LeftButton
        event = QtGui.QMouseEvent(kind, local, self.view.mapToGlobal(local),
                                  button, held, modifiers)
        handler = {QtCore.QEvent.MouseButtonPress: self.view.mousePressEvent,
                   QtCore.QEvent.MouseMove: self.view.mouseMoveEvent,
                   QtCore.QEvent.MouseButtonRelease:
                       self.view.mouseReleaseEvent}[kind]
        handler(event)
        app.processEvents()

    def drag(self, start, end, modifiers=QtCore.Qt.NoModifier,
             press_modifiers=None):
        if press_modifiers is None:
            press_modifiers = modifiers
        self.mouse(QtCore.QEvent.MouseButtonPress, start,
                   modifiers=press_modifiers)
        mid = ((start[0] + end[0]) * .5, (start[1] + end[1]) * .5)
        self.mouse(QtCore.QEvent.MouseMove, mid, modifiers=modifiers)
        self.mouse(QtCore.QEvent.MouseMove, end, modifiers=modifiers)
        self.mouse(QtCore.QEvent.MouseButtonRelease, end, modifiers=modifiers)



class BackdropsInTheView(ViewCase):
    """Grabbing, moving and resizing one with the mouse."""

    def test_it_is_drawn_behind_the_nodes(self):
        backdrop_id = self.add()
        graphic = self.view.get_backdrop_graphic(backdrop_id)
        self.assertIsInstance(graphic, BackdropGraphicsItem)
        node = self.view.get_node_graphic('/inside')
        self.assertLess(graphic.zValue(), node.zValue())
        self.assertLess(graphic.zValue(), self.view.CONNECTION_DEPTH)

    def test_dragging_the_header_moves_the_nodes_inside(self):
        backdrop_id = self.add()
        child_before = self.view.get_node_graphic('/inside/child').scenePos()
        self.drag((-50, -90), (150, -40))
        self.assertEqual([100.0, -50.0],
                         self.model.get_backdrop(backdrop_id)['pos'])
        self.assertEqual([200.0, 50.0], self.node_pos('/inside'))
        self.assertEqual([1200.0, 0.0], self.node_pos('/outside'))
        child_after = self.view.get_node_graphic('/inside/child').scenePos()
        self.assertEqual(QtCore.QPointF(200, 50), child_after - child_before)

    def test_one_undo_puts_the_backdrop_and_its_nodes_back(self):
        backdrop_id = self.add()
        count = self.model.undo_stack.count()
        self.drag((-50, -90), (150, -40))
        self.assertEqual(count + 1, self.model.undo_stack.count())
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([-100.0, -100.0],
                         self.model.get_backdrop(backdrop_id)['pos'])
        self.assertEqual([0.0, 0.0], self.node_pos('/inside'))
        graphic = self.view.get_backdrop_graphic(backdrop_id)
        self.assertEqual(QtCore.QPointF(-100, -100), graphic.pos())
        self.assertEqual(QtCore.QPointF(0, 0),
                         self.view.get_node_graphic('/inside').pos())

    def test_ctrl_drag_moves_the_backdrop_alone(self):
        backdrop_id = self.add()
        self.drag((-50, -90), (150, -40), modifiers=QtCore.Qt.ControlModifier)
        self.assertEqual([100.0, -50.0],
                         self.model.get_backdrop(backdrop_id)['pos'])
        self.assertEqual([0.0, 0.0], self.node_pos('/inside'))

    def test_a_backdrop_inside_another_moves_with_it(self):
        outer = self.add(pos=(-200, -200), size=(1000, 700))
        inner = self.add(pos=(-100, -100), size=(600, 400))
        self.drag((-150, -190), (-50, -190))
        self.assertEqual([0.0, -100.0], self.model.get_backdrop(inner)['pos'])
        self.assertEqual([-100.0, -200.0],
                         self.model.get_backdrop(outer)['pos'])
        self.assertEqual([100.0, 0.0], self.node_pos('/inside'))

    def test_the_corner_resizes_it(self):
        backdrop_id = self.add()
        self.drag((495, 295), (695, 395))
        self.assertEqual([800.0, 500.0],
                         self.model.get_backdrop(backdrop_id)['size'])
        self.assertEqual([0.0, 0.0], self.node_pos('/inside'))

    def test_it_cannot_be_made_smaller_than_the_minimum(self):
        backdrop_id = self.add()
        self.drag((495, 295), (-900, -900))
        self.assertEqual(list(backdrops.MIN_SIZE),
                         self.model.get_backdrop(backdrop_id)['size'])

    def test_the_body_does_not_take_the_mouse(self):
        backdrop_id = self.add()
        # Below the header and away from the nodes and the corner.
        self.drag((450, 200), (600, 250))
        self.assertEqual([-100.0, -100.0],
                         self.model.get_backdrop(backdrop_id)['pos'])
        self.assertIsNone(self.view._backdrop_drag)

    def test_the_note_sits_at_the_top_left_and_grows_the_header(self):
        backdrop_id = self.add()
        graphic = self.view.get_backdrop_graphic(backdrop_id)
        bare = graphic.header_rect().height()
        self.model.edit_backdrop(backdrop_id,
                                 note='First line\nSecond line\nThird line')
        app.processEvents()
        note = graphic._note_rect()
        self.assertEqual(graphic.PADDING, note.left())
        self.assertLess(note.top(), 80)
        self.assertGreater(graphic.header_rect().height(), bare)
        self.assertEqual('First line\nSecond line\nThird line',
                         graphic.toolTip())

    def test_adding_one_around_the_selection(self):
        self.model.set_selection(['/inside/child'])
        backdrop_id = self.view.add_backdrop()
        app.processEvents()
        graphic = self.view.get_backdrop_graphic(backdrop_id)
        nodes, _ = self.view.backdrop_contents(graphic)
        self.assertEqual(['/inside'], [n.node_path for n in nodes])
        area = graphic.scene_rect()
        node = self.view.get_node_graphic('/inside')
        self.assertTrue(area.contains(self.view._nodes_rect([node])))
        self.assertGreaterEqual(
            self.view._nodes_rect([node]).top() - area.top(),
            graphic.header_rect().height())
        self.assertEqual([backdrop_id], self.view.selected_backdrops)
        self.assertEqual([], self.model.selection)
        self.model.undo_stack.undo()
        self.assertIsNone(self.model.get_backdrop(backdrop_id))
        self.assertEqual(['/inside/child'], self.model.selection)

    def test_delete_takes_the_backdrop_and_leaves_the_nodes(self):
        backdrop_id = self.add()
        self.mouse(QtCore.QEvent.MouseButtonPress, (-50, -90))
        self.mouse(QtCore.QEvent.MouseButtonRelease, (-50, -90))
        self.assertEqual([backdrop_id], self.view.selected_backdrops)
        self.win.node_actions.delete_node_action.trigger()
        app.processEvents()
        self.assertIsNone(self.model.get_backdrop(backdrop_id))
        self.assertIsNone(self.view.get_backdrop_graphic(backdrop_id))
        self.assertIsNotNone(self.model.comp_layer.lookup('/inside'))

    def test_its_hotkey_is_not_shared(self):
        # Qt fires neither action when two share a key.
        action = self.win.node_actions.add_backdrop_action
        key = action.shortcut()
        self.assertFalse(key.isEmpty())
        shared = [a.text() for a in self.win.findChildren(QtWidgets.QAction)
                  if a is not action and a.shortcut() == key]
        self.assertEqual([], shared)

    def test_clicking_elsewhere_lets_go_of_it(self):
        backdrop_id = self.add()
        self.mouse(QtCore.QEvent.MouseButtonPress, (-50, -90))
        self.mouse(QtCore.QEvent.MouseButtonRelease, (-50, -90))
        self.mouse(QtCore.QEvent.MouseButtonPress, (2000, 2000))
        self.mouse(QtCore.QEvent.MouseButtonRelease, (2000, 2000))
        self.assertEqual([], self.view.selected_backdrops)
        self.assertIsNotNone(self.model.get_backdrop(backdrop_id))

    def test_fit_to_nodes_inside(self):
        backdrop_id = self.add(pos=(-300, -300), size=(1200, 900))
        self.view.fit_backdrop(backdrop_id)
        app.processEvents()
        graphic = self.view.get_backdrop_graphic(backdrop_id)
        node = self.view.get_node_graphic('/inside')
        self.assertLess(graphic.width, 1200)
        self.assertTrue(graphic.scene_rect().contains(
            self.view._nodes_rect([node])))

    def test_the_mini_map_draws_it(self):
        backdrop_id = self.add()
        graphic = self.view.get_backdrop_graphic(backdrop_id)
        rects = [r for r, _ in self.view.mini_map._node_blocks()]
        self.assertIn(graphic.scene_rect(), rects)


class ChildrenFollowTheirParent(ViewCase):
    """A child node is stacked under its parent by being made a child
    item of it. NodeGraphicsItem used to override itemChange, and with
    PySide6 6.9 that alone made setParentItem do nothing, so children were
    left behind by whatever moved their parent, a backdrop included."""

    def child_offset(self):
        parent = self.view.get_node_graphic('/inside')
        child = self.view.get_node_graphic('/inside/child')
        return child.scenePos() - parent.scenePos()

    def test_a_child_is_a_child_item_of_its_parent(self):
        parent = self.view.get_node_graphic('/inside')
        child = self.view.get_node_graphic('/inside/child')
        self.assertIs(parent, child.parentItem())

    def test_dragging_the_parent_takes_the_child(self):
        offset = self.child_offset()
        self.drag((100, 15), (400, 215))
        self.assertEqual([300.0, 200.0], self.node_pos('/inside'))
        self.assertEqual(offset, self.child_offset())

    def test_shift_dragging_snaps_to_the_grid(self):
        grid = self.view.draw_grid_size
        # Shift on the press toggles the selection, as with any node, so
        # it is held while moving.
        self.drag((100, 15), (237, 129), modifiers=QtCore.Qt.ShiftModifier,
                  press_modifiers=QtCore.Qt.NoModifier)
        x, y = self.node_pos('/inside')
        self.assertEqual((0, 0), (x % grid, y % grid))
        self.assertNotEqual([0.0, 0.0], [x, y])

    def test_moving_a_backdrop_and_undoing_it_keeps_the_child(self):
        self.add()
        offset = self.child_offset()
        self.drag((-50, -90), (150, -40))
        self.assertEqual(offset, self.child_offset())
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([0.0, 0.0], self.node_pos('/inside'))
        self.assertEqual(offset, self.child_offset())

    def test_a_moving_parent_keeps_the_childs_connections_drawn(self):
        child = self.view.get_node_graphic('/inside/child')
        seen = []
        original = self.view.get_node_connection_graphics

        def watched(node_path):
            seen.append(node_path)
            return original(node_path)
        with mock.patch.object(self.view, 'get_node_connection_graphics',
                               side_effect=watched):
            self.view.get_node_graphic('/inside').setPos(50, 50)
        self.assertIn(child.node_path, seen)


if __name__ == '__main__':
    unittest.main()
