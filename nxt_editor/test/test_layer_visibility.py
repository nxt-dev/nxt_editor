"""A layer can be hidden in the graph without being taken out of it.

A library layer of nodes that are only there to be instanced fills the
graph of every layer above it. Muting it is not an answer, the graph needs
it to build. The eye in the Layer Manager hides what only that layer has:
the nodes no layer still showing has an opinion on, unless something under
them is shown, the lines to and from them, and its backdrops. The comp
does not change, so the graph builds the same.

It is a view, kept per user and per graph in the editor's cache. It never
marks a layer unsaved.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

# External
from Qt import QtCore, QtGui, QtTest, QtWidgets

# Internal
from nxt import nxt_node
from nxt.session import Session
from nxt_editor import stage_model, user_dir
from nxt_editor import connection_graphics_item as lines
from nxt_editor.dockwidgets.layer_manager import (EyeCheckboxDelegate,
                                                   LayerModel)
from nxt_editor.test.test_paste_is_one_undo import Pasteboard

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


def write(path, data):
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


class LayerVisibility(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_layer_eye_'))
        # Nobody's real editor cache.
        cls.cache_key = user_dir.EDITOR_CACHE.HIDDEN_LAYERS
        cls.cache_before = user_dir.editor_cache.get(cls.cache_key) or {}
        user_dir.editor_cache[cls.cache_key] = {}
        cls.library = write(os.path.join(cls.tmp, 'library.nxt'), {
            'version': '1.17', 'alias': 'library', 'references': [],
            'meta_data': {'backdrops': {'bd_lib': {
                'pos': [0, -300], 'size': [400, 200], 'title': 'Library'}}},
            'nodes': {'/template': {'attrs': {'size': {'value': '1'}}},
                      '/start': {'code': ['pass']}}})
        cls.top = write(os.path.join(cls.tmp, 'top.nxt'), {
            'version': '1.17', 'alias': 'top', 'references': ['library.nxt'],
            'meta_data': {'backdrops': {'bd_top': {
                'pos': [0, 300], 'size': [400, 200], 'title': 'Top'}}},
            'nodes': {'/made': {'instance': '/template'},
                      '/start/step': {'code': ['pass']}}})
        cls.win = MainWindow(filepath=cls.top)
        cls.win.show()
        app.processEvents()
        cls.model = cls.win.model
        cls.view = cls.win.get_current_view()
        cls.library_layer = cls.model.stage._sub_layers[1]

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        user_dir.editor_cache[cls.cache_key] = cls.cache_before
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.hide(False)

    def tearDown(self):
        self.hide(False)

    def hide(self, hidden=True):
        self.model.set_layer_hidden(self.library_layer.real_path, hidden)
        app.processEvents()

    def shown(self, node_path):
        return self.view.get_node_graphic(node_path).isVisible()

    # -- what is hidden ----------------------------------------------------

    def test_every_layer_shows_to_begin_with(self):
        self.assertFalse(self.model.hidden_layer_paths())
        for path in ('/template', '/start', '/made'):
            self.assertTrue(self.shown(path), path)

    def test_a_node_only_the_hidden_layer_has_is_hidden(self):
        self.hide()
        self.assertFalse(self.shown('/template'))

    def test_a_node_another_layer_adds_to_stays(self):
        # /start comes from the library, but the top layer put a step
        # under it. Hiding the library must not take that out of sight.
        self.hide()
        self.assertTrue(self.shown('/start'))
        self.assertTrue(self.shown('/start/step'))

    def test_the_other_layers_nodes_stay(self):
        self.hide()
        self.assertTrue(self.shown('/made'))

    def test_lines_to_a_hidden_node_are_hidden(self):
        self.hide()
        lines = [g for g in self.view._connection_graphics
                 if '/template' in (g.src_node_path, g.tgt_node_path)]
        self.assertTrue(lines, 'the instance line was never drawn')
        self.assertFalse(any(line.isVisible() for line in lines))

    def test_its_backdrops_are_hidden_and_others_are_not(self):
        self.hide()
        self.assertFalse(self.view.get_backdrop_graphic('bd_lib').isVisible())
        self.assertTrue(self.view.get_backdrop_graphic('bd_top').isVisible())

    def test_showing_it_again_brings_everything_back(self):
        self.hide()
        self.hide(False)
        self.assertTrue(self.shown('/template'))
        self.assertTrue(self.view.get_backdrop_graphic('bd_lib').isVisible())
        self.assertTrue(all(g.isVisible()
                            for g in self.view._connection_graphics))

    def test_a_redraw_keeps_it_hidden(self):
        self.hide()
        self.view.update_view()
        app.processEvents()
        self.assertFalse(self.shown('/template'))
        self.assertTrue(self.shown('/made'))

    def test_frame_all_ignores_what_is_hidden(self):
        # Moved on the item, not in the model: this is about what is
        # framed, and a model move would leave the layer unsaved.
        graphic = self.view.get_node_graphic('/template')
        before = graphic.pos()
        graphic.setPos(9000.0, 9000.0)
        self.addCleanup(graphic.setPos, before)
        self.hide()
        with mock.patch.object(self.view, 'frame_rect') as frame_rect:
            self.view.frame_all()
        rect = frame_rect.call_args[0][0]
        self.assertLess(rect.right(), 9000)

    # -- what it leaves alone ----------------------------------------------

    def test_the_graph_is_still_the_same_graph(self):
        before = sorted(self.model.get_descendants('/'))
        self.hide()
        self.assertEqual(before, sorted(self.model.get_descendants('/')))
        self.assertTrue(self.model.node_exists('/template'))

    def test_nothing_is_marked_unsaved(self):
        self.hide()
        self.assertFalse(self.model.effected_layers)

    # -- remembered, and shown in the layer manager ------------------------

    def test_it_is_remembered_for_this_graph(self):
        self.hide()
        stored = user_dir.editor_cache[user_dir.EDITOR_CACHE.HIDDEN_LAYERS]
        self.assertEqual([self.library_layer.real_path],
                         stored[self.model.top_layer.real_path])
        # Another model on the same graph, as opening it again makes.
        again = stage_model.StageModel(Session().load_file(self.top))
        self.assertTrue(again.get_layer_hidden(
            again.stage._sub_layers[1].real_path))

    def test_showing_every_layer_forgets_the_graph(self):
        self.hide()
        self.hide(False)
        stored = user_dir.editor_cache[user_dir.EDITOR_CACHE.HIDDEN_LAYERS]
        self.assertNotIn(self.model.top_layer.real_path, stored)

    def test_the_eye_column_follows_and_toggles(self):
        layer_model = LayerModel(self.model)
        index = layer_model.get_index_of_layer(self.library_layer)
        eye = layer_model.index(index.row(), LayerModel.VISIBLE_COLUMN,
                                index.parent())
        role = QtCore.Qt.CheckStateRole
        self.assertEqual(QtCore.Qt.Checked, layer_model.data(eye, role))
        layer_model.setData(eye, False, role)
        self.assertTrue(self.model.get_layer_hidden(
            self.library_layer.real_path))
        self.assertEqual(QtCore.Qt.Unchecked, layer_model.data(eye, role))

    def test_clicking_the_eye_hides_and_clicking_again_shows(self):
        # Through the view, the way a person does it. The delegate hands
        # the model a value worked out from an option it never filled in,
        # so a click that trusted it showed the layer every time.
        tree = self.win.layer_manager.layer_tree
        layer_model = tree.model()
        index = layer_model.get_index_of_layer(self.library_layer)
        eye = layer_model.index(index.row(), LayerModel.VISIBLE_COLUMN,
                                index.parent())
        spot = tree.visualRect(eye).center()
        path = self.library_layer.real_path
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton,
                                pos=spot)
        self.assertTrue(self.model.get_layer_hidden(path))
        self.assertFalse(self.shown('/template'))
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton,
                                pos=spot)
        self.assertFalse(self.model.get_layer_hidden(path))
        self.assertTrue(self.shown('/template'))

    def test_two_quick_clicks_on_the_eye_hide_and_show(self):
        tree = self.win.layer_manager.layer_tree
        layer_model = tree.model()
        index = layer_model.get_index_of_layer(self.library_layer)
        eye = layer_model.index(index.row(), LayerModel.VISIBLE_COLUMN,
                                index.parent())
        spot = tree.visualRect(eye).center()
        path = self.library_layer.real_path
        # What two quick clicks send: the second press is a double click.
        port, left = tree.viewport(), QtCore.Qt.LeftButton
        QtTest.QTest.mousePress(port, left, pos=spot)
        QtTest.QTest.mouseRelease(port, left, pos=spot)
        self.assertTrue(self.model.get_layer_hidden(path))
        QtTest.QTest.mouseDClick(port, left, pos=spot)
        QtTest.QTest.mouseRelease(port, left, pos=spot)
        self.assertFalse(self.model.get_layer_hidden(path))
        self.assertTrue(self.shown('/template'))

    def test_the_mini_map_leaves_its_backdrops_out(self):
        def backdrop_rects():
            rects = [self.view.get_backdrop_graphic(name).scene_rect()
                     for name in ('bd_lib', 'bd_top')]
            drawn = [rect for rect, _color in self.view.mini_map._node_blocks()]
            return [rect in drawn for rect in rects]
        self.assertEqual(backdrop_rects(), [True, True])
        self.hide()
        self.assertEqual(backdrop_rects(), [False, True])


class _SameGraph(unittest.TestCase):
    """The graph LayerVisibility opens, in a window of its own, for tests
    that change more than which layers are hidden."""

    setUpClass = classmethod(LayerVisibility.setUpClass.__func__)
    tearDownClass = classmethod(LayerVisibility.tearDownClass.__func__)
    setUp = LayerVisibility.setUp
    tearDown = LayerVisibility.tearDown
    hide = LayerVisibility.hide
    shown = LayerVisibility.shown

    def line_to(self, node_path):
        for line in self.view._connection_graphics:
            if node_path in (line.src_node_path, line.tgt_node_path):
                return line
        self.fail('no line to {} was drawn'.format(node_path))


class TheEye(unittest.TestCase):

    def test_the_eye_paints(self):
        # It was cut out with QMarginsF, which Qt.py 1.4 does not have, so
        # under it every paint raised and the Layer Manager never drew.
        model = QtGui.QStandardItemModel(1, 1)
        item = QtGui.QStandardItem()
        item.setCheckable(True)
        item.setCheckState(QtCore.Qt.Checked)
        model.setItem(0, 0, item)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 24, 24)
        pixmap = QtGui.QPixmap(24, 24)
        pixmap.fill(QtCore.Qt.transparent)
        blank = pixmap.toImage()
        painter = QtGui.QPainter(pixmap)
        try:
            EyeCheckboxDelegate().paint(painter, option, model.index(0, 0))
        finally:
            painter.end()
        self.assertNotEqual(blank, pixmap.toImage())


class HiddenLines(_SameGraph):
    """One rule decides whether a line is drawn, see StageView.line_shown,
    so showing a layer again cannot bring back a line another rule hides,
    and a line drawn later is hidden like the rest."""

    def implied_lines(self, shown):
        self.view.toggle_implicit_connections(shown)
        app.processEvents()

    def test_every_line_follows_the_one_rule(self):
        self.hide()
        self.assertTrue(self.view._connection_graphics)
        for line in self.view._connection_graphics:
            self.assertEqual(self.view.line_shown(line), line.isVisible())

    def test_showing_the_layer_leaves_implied_lines_off(self):
        self.addCleanup(self.implied_lines, True)
        self.implied_lines(False)
        self.hide()
        self.hide(False)
        implied = (nxt_node.INTERNAL_ATTRS.INSTANCE_PATH,
                   nxt_node.INTERNAL_ATTRS.COMPUTE)
        for line in self.view._connection_graphics:
            if line.tgt_attr_name in implied:
                self.assertFalse(line.isVisible(), line.tgt_path)

    def test_turning_implied_lines_on_keeps_hidden_ones_hidden(self):
        self.addCleanup(self.implied_lines, True)
        self.hide()
        self.implied_lines(False)
        self.implied_lines(True)
        self.assertFalse(self.line_to('/template').isVisible())

    def test_a_line_drawn_later_is_hidden(self):
        self.hide()
        self.view._draw_inst_connections('/made')
        self.assertFalse(self.line_to('/template').isVisible())

    def test_applying_works_out_hidden_nodes_once(self):
        model = self.model
        with mock.patch.object(model, 'hidden_nodes',
                               wraps=model.hidden_nodes) as hidden_nodes:
            with mock.patch.object(model, 'is_node_hidden') as per_node:
                self.hide()
        self.assertEqual(1, hidden_nodes.call_count)
        per_node.assert_not_called()

    def test_points_on_a_hidden_line_are_hidden_and_not_box_selected(self):
        # On the line itself, not in the model: points are saved in the
        # layer, and this is about what is drawn.
        line = self.line_to('/template')
        line.set_points([[50.0, 50.0]])
        self.addCleanup(line.set_points, [])
        everywhere = QtCore.QRectF(-1e6, -1e6, 2e6, 2e6)
        self.assertTrue(self.view.points_in(everywhere))
        self.hide()
        self.assertFalse(line.point_graphics[0].isVisible())
        self.assertFalse(self.view.points_in(everywhere))


class HiddenSelection(_SameGraph):
    """What cannot be seen cannot be selected from the graph, so copy and
    delete only reach what is showing."""

    def tearDown(self):
        self.model.clear_selection()
        super(HiddenSelection, self).tearDown()

    def test_select_all_leaves_hidden_nodes_out(self):
        self.hide()
        self.view.select_all()
        self.assertNotIn('/template', self.model.selection)
        self.assertIn('/made', self.model.selection)

    def test_box_select_leaves_hidden_nodes_out(self):
        self.view.toggle_mini_map(False)
        self.addCleanup(self.view.toggle_mini_map, self.view.show_mini_map)
        self.view.frame_all()
        app.processEvents()
        self.hide()
        viewport = self.view.viewport()
        corner = viewport.rect().bottomRight() - QtCore.QPoint(2, 2)
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton,
                                pos=QtCore.QPoint(2, 2))
        QtTest.QTest.mouseMove(viewport, corner)
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton,
                                  pos=corner)
        self.assertIn('/made', self.model.selection)
        self.assertNotIn('/template', self.model.selection)

    def test_hiding_a_layer_takes_its_nodes_out_of_the_selection(self):
        self.model.set_selection(['/template', '/made'])
        self.hide()
        self.assertEqual(['/made'], list(self.model.selection))


class FramingHiddenNodes(_SameGraph):
    """Framing leaves hidden nodes out. With only hidden nodes to frame
    the view stays where it is and says why, rather than showing the
    layer: picking a node in the Outliner would otherwise bring a whole
    library back into the graph."""

    def test_framing_a_hidden_node_stays_put_and_says_why(self):
        self.hide()
        with mock.patch.object(self.view, 'frame_rect') as frame_rect:
            self.model.select_and_frame('/template')
        frame_rect.assert_not_called()
        self.assertIn('/template', self.view.status_label.text())
        self.assertTrue(self.model.get_layer_hidden(
            self.library_layer.real_path))
        self.model.clear_selection()

    def test_framing_some_hidden_nodes_frames_the_rest(self):
        graphic = self.view.get_node_graphic('/template')
        before = graphic.pos()
        graphic.setPos(9000.0, 9000.0)
        self.addCleanup(graphic.setPos, before)
        self.hide()
        with mock.patch.object(self.view, 'frame_rect') as frame_rect:
            self.view.frame_nodes(['/template', '/made'])
        rect = frame_rect.call_args[0][0]
        self.assertLess(rect.right(), 9000)

    def test_going_to_a_hidden_node_stays_put_and_says_why(self):
        # Go to Source or Target on a line, here or in the Instance View.
        self.hide()
        with mock.patch.object(self.view, 'centerOn') as center_on:
            self.view.go_to_node('/template')
        center_on.assert_not_called()
        self.assertIn('/template', self.view.status_label.text())
        self.assertTrue(self.model.get_layer_hidden(
            self.library_layer.real_path))
        self.model.clear_selection()

    def test_going_to_a_node_in_view_centers_on_it(self):
        self.hide()
        with mock.patch.object(self.view, 'centerOn') as center_on:
            self.view.go_to_node('/made')
        center_on.assert_called_once()
        self.model.clear_selection()


class HiddenExecLines(_SameGraph):
    """Exec lines are always drawn, except to or from a hidden node."""

    def exec_line(self, src, tgt):
        return types.SimpleNamespace(
            kind=lines.EXEC_LINES, src_node_path=src, tgt_node_path=tgt,
            src_attr_name=nxt_node.INTERNAL_ATTRS.EXECUTE_IN,
            tgt_attr_name=nxt_node.INTERNAL_ATTRS.EXECUTE_IN)

    def test_an_exec_line_to_a_hidden_node_is_hidden(self):
        self.hide()
        self.assertFalse(self.view.line_shown(
            self.exec_line('/made', '/template')))
        self.assertFalse(self.view.line_shown(
            self.exec_line('/template', '/made')))

    def test_other_exec_lines_are_still_drawn(self):
        self.hide()
        self.assertTrue(self.view.line_shown(
            self.exec_line('/made', '/made')))


class MakingNodesOnAHiddenLayer(_SameGraph):
    """A node made on a hidden target layer would vanish as it was made,
    so the layer is shown again, and the graph says so."""

    def setUp(self):
        super(MakingNodesOnAHiddenLayer, self).setUp()
        self.messages = []
        self.model.status_message.connect(self.messages.append)
        self.model.clipboard = Pasteboard()
        self.model.set_target_layer(self.library_layer.real_path)

    def tearDown(self):
        self.model.status_message.disconnect(self.messages.append)
        # Undone on the layer it was done on: undoing a parent looks the
        # nodes up on the target layer.
        while self.model.undo_stack.canUndo():
            self.model.undo_stack.undo()
        self.model.set_target_layer(self.model.top_layer.real_path)
        app.processEvents()
        super(MakingNodesOnAHiddenLayer, self).tearDown()

    def assert_shown_again(self, node_path):
        self.assertFalse(self.model.get_layer_hidden(
            self.library_layer.real_path))
        self.assertTrue(self.shown(node_path))
        self.assertEqual(1, len(self.messages))
        self.assertIn('library', self.messages[0])
        self.assertIn('library', self.view.status_label.text())

    def test_a_new_node_shows_the_layer(self):
        self.hide()
        path = self.model.add_node(name='fresh', pos=[0.0, 0.0],
                                   layer=self.model.target_layer)
        app.processEvents()
        self.assert_shown_again(path)

    def test_a_pasted_node_shows_the_layer(self):
        self.model.copy_nodes(['/template'])
        self.hide()
        pasted = self.model.paste_nodes(pos=[0.0, 0.0],
                                        layer=self.model.target_layer)
        app.processEvents()
        self.assert_shown_again(pasted[0])

    def test_a_node_made_under_a_node_in_view_shows_the_layer(self):
        # /start shows, the top layer adds to it. Nodes are hidden one at
        # a time, so a node made under it that only the hidden layer has
        # would still vanish: the layer is shown again. While whole trees
        # were hidden it was in view already and the layer stayed hidden.
        self.hide()
        self.model.add_node(name='more', parent_path='/start',
                            layer=self.model.target_layer)
        app.processEvents()
        self.assert_shown_again('/start/more')

    def test_a_node_parented_out_of_sight_shows_the_layer(self):
        # As the Outliner does when rows are dragged onto another.
        self.model.add_node(name='holder', pos=[0.0, 0.0],
                            layer=self.model.target_layer)
        self.model.add_node(name='moved', pos=[0.0, 200.0],
                            layer=self.model.target_layer)
        app.processEvents()
        self.hide()
        self.model.parent_nodes(['/moved'], '/holder')
        app.processEvents()
        self.assertFalse(self.model.get_layer_hidden(
            self.library_layer.real_path))
        self.assertTrue(self.shown('/holder/moved'))
        self.assertEqual(1, len(self.messages))
        self.assertIn('parented', self.messages[0])


class LayoutAndFramingLeaveHiddenNodesOut(_SameGraph):
    """Layout Nodes and framing a graph as it opens only reach what is
    showing."""

    def test_layout_leaves_hidden_nodes_where_they_are(self):
        self.model.clear_selection()
        self.hide()
        with mock.patch.object(self.model, 'set_nodes_pos') as set_pos:
            self.view.layout_nodes()
        moved = set()
        for call in set_pos.call_args_list:
            moved.update(call[0][0])
        self.assertIn('/made', moved)
        self.assertNotIn('/template', moved)

    def test_framing_on_open_leaves_hidden_nodes_out(self):
        graphic = self.view.get_node_graphic('/template')
        before = graphic.pos()
        graphic.setPos(9000.0, 9000.0)
        self.addCleanup(graphic.setPos, before)
        self.hide()
        with mock.patch.object(self.view, 'frame_rect') as frame_rect:
            self.view.frame_opened()
        rect = frame_rect.call_args[0][0]
        self.assertLess(rect.right(), 9000)


class LayeredRig(unittest.TestCase):
    """A rig built up in layers, as a character is: a base layer makes
    /load and the steps under it, a mid layer adds a step and changes one
    of the base's, and a show layer adds steps of its own under /load and
    a root of its own. Nodes are hidden one at a time, so hiding the show
    layer takes away its own steps even though /load is everybody's."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_layer_eye_'))
        cls.cache_key = user_dir.EDITOR_CACHE.HIDDEN_LAYERS
        cls.cache_before = user_dir.editor_cache.get(cls.cache_key) or {}
        user_dir.editor_cache[cls.cache_key] = {}
        write(os.path.join(cls.tmp, 'base.nxt'), {
            'version': '1.17', 'alias': 'base', 'references': [],
            'nodes': {'/load': {'code': ['pass']},
                      '/load/a': {'attrs': {'v': {'value': '1'}}},
                      '/load/b': {'attrs': {'v': {'value': '1'}}},
                      '/load/c': {},
                      '/keep': {},
                      '/parts': {},
                      '/parts/kid': {}}})
        write(os.path.join(cls.tmp, 'mid.nxt'), {
            'version': '1.17', 'alias': 'mid', 'references': ['base.nxt'],
            'nodes': {'/load/b': {'attrs': {'v': {'value': '2'}}},
                      '/load/m': {}}})
        write(os.path.join(cls.tmp, 'show.nxt'), {
            'version': '1.17', 'alias': 'show', 'references': ['mid.nxt'],
            'nodes': {'/load': {'child_order': ['a', 's1', 'b', 'c', 'm',
                                                's2']},
                      '/load/s1': {},
                      '/load/s2': {'instance': '/load/c'},
                      '/keep/x': {},
                      '/show_root': {'execute_in': '/load'},
                      '/show_root/kid': {}}})
        cls.top = write(os.path.join(cls.tmp, 'top.nxt'), {
            'version': '1.17', 'alias': 'top', 'references': ['show.nxt'],
            'nodes': {'/made': {'instance': '/parts'}}})
        cls.win = MainWindow(filepath=cls.top)
        cls.win.show()
        app.processEvents()
        cls.model = cls.win.model
        cls.view = cls.win.get_current_view()
        cls.layers = dict((layer.get_alias(), layer.real_path)
                          for layer in cls.model.stage._sub_layers)

    @classmethod
    def tearDownClass(cls):
        # Undone, but still marked unsaved, which would ask to save.
        cls.model.effected_layers.clear()
        LayerVisibility.tearDownClass.__func__(cls)

    def setUp(self):
        self.hide(*self.layers, hidden=False)

    def tearDown(self):
        self.model.clear_selection()
        self.hide(*self.layers, hidden=False)

    def hide(self, *aliases, **kwargs):
        for alias in aliases:
            self.model.set_layer_hidden(self.layers[alias],
                                        kwargs.get('hidden', True))
        app.processEvents()

    def shown(self, node_path):
        return self.view.get_node_graphic(node_path).isVisible()

    def undo_all(self):
        while self.model.undo_stack.canUndo():
            self.model.undo_stack.undo()

    def assert_shown(self, *node_paths):
        for path in node_paths:
            self.assertTrue(self.shown(path), path)
            self.assertFalse(self.view.node_hidden(path), path)

    def assert_hidden(self, *node_paths):
        for path in node_paths:
            self.assertFalse(self.shown(path), path)
            self.assertTrue(self.view.node_hidden(path), path)

    def child_y(self, node_path):
        return self.view.get_node_graphic(node_path).pos().y()

    # -- what is hidden ----------------------------------------------------

    def test_hiding_the_show_layer_hides_its_own_nodes(self):
        self.hide('show')
        self.assert_hidden('/load/s1', '/load/s2', '/keep/x', '/show_root',
                           '/show_root/kid')

    def test_hiding_the_show_layer_keeps_base_and_changed_nodes(self):
        # /load has the show layer's child order, but the base layer has
        # it too.
        self.hide('show')
        self.assert_shown('/load', '/load/a', '/load/b', '/load/c',
                          '/load/m', '/keep', '/made')

    def test_hiding_base_keeps_what_a_layer_showing_adds_to(self):
        self.hide('base')
        # /load/b is changed by mid, and every layer adds to /load.
        self.assert_shown('/load', '/load/b', '/load/m', '/load/s1',
                          '/load/s2', '/keep', '/keep/x')
        self.assert_hidden('/load/a', '/load/c', '/parts', '/parts/kid')

    def test_a_parent_shows_while_a_child_does(self):
        # /keep is the base layer's, /keep/x the show layer's.
        self.hide('base')
        self.assert_shown('/keep', '/keep/x')
        self.hide('show')
        self.assert_hidden('/keep', '/keep/x')

    def test_hiding_every_layer_hides_every_node(self):
        self.hide(*self.layers)
        for path in self.view._node_graphics:
            self.assertFalse(self.shown(path), path)

    def test_the_hidden_nodes_are_one_answer(self):
        self.hide('show')
        self.assertEqual({'/load/s1', '/load/s2', '/keep/x', '/show_root',
                          '/show_root/kid'}, set(self.model.hidden_nodes()))

    # -- instanced nodes ---------------------------------------------------

    def test_a_proxy_goes_with_the_node_it_is_under(self):
        # /made/kid is made by the instance of /parts. Hiding the layer
        # /parts is on leaves the instance, and what it brings, in view.
        self.assertTrue(self.model.get_node_is_proxy('/made/kid'))
        self.hide('base')
        self.assert_hidden('/parts', '/parts/kid')
        self.assert_shown('/made', '/made/kid')

    def test_a_proxy_is_hidden_with_its_instance(self):
        self.hide('top')
        self.assert_hidden('/made', '/made/kid')
        self.assert_shown('/parts', '/parts/kid')

    # -- the stack under a parent ------------------------------------------

    def test_children_close_up_over_a_hidden_child(self):
        order = ['/load/a', '/load/s1', '/load/b', '/load/c', '/load/m',
                 '/load/s2']
        self.assertEqual(order, self.model.get_children(
            '/load', ordered=True, include_implied=True))
        before = dict((path, self.child_y(path)) for path in order)
        height = self.view.get_node_graphic('/load').stack_height
        self.hide('show')
        # /load/b moves up to where /load/s1 was, and the rest with it.
        self.assertEqual(before['/load/a'], self.child_y('/load/a'))
        self.assertEqual(before['/load/s1'], self.child_y('/load/b'))
        self.assertEqual(before['/load/b'], self.child_y('/load/c'))
        self.assertEqual(before['/load/c'], self.child_y('/load/m'))
        self.assertLess(self.view.get_node_graphic('/load').stack_height,
                        height)
        self.hide('show', hidden=False)
        for path in order:
            self.assertEqual(before[path], self.child_y(path), path)
        self.assertEqual(height,
                         self.view.get_node_graphic('/load').stack_height)

    def test_a_parent_with_every_child_hidden_has_no_room_under_it(self):
        self.hide('show')
        graphic = self.view.get_node_graphic('/keep')
        own = graphic.get_selection_rect().height()
        self.assertEqual(own, graphic.stack_height)
        self.assertEqual(own, graphic.stack_bounding_rect.height())

    def test_a_redraw_keeps_the_stack_closed_up(self):
        self.hide('show')
        closed = self.child_y('/load/b')
        self.view.update_view()
        app.processEvents()
        self.assert_hidden('/load/s1')
        self.assertEqual(closed, self.child_y('/load/b'))

    # -- lines, selection and framing --------------------------------------

    def lines_to(self, node_path):
        return [line for line in self.view._connection_graphics
                if node_path in (line.src_node_path, line.tgt_node_path)]

    def test_lines_to_a_hidden_child_and_root_are_hidden(self):
        instance_lines = self.lines_to('/load/s2')
        exec_lines = self.lines_to('/show_root')
        self.assertTrue(instance_lines, 'the instance line was never drawn')
        self.assertTrue(exec_lines, 'the exec line was never drawn')
        self.hide('show')
        for line in instance_lines + exec_lines:
            self.assertFalse(line.isVisible())
        for line in self.view._connection_graphics:
            self.assertEqual(self.view.line_shown(line), line.isVisible())

    def test_select_all_leaves_hidden_children_out(self):
        self.hide('show')
        self.view.select_all()
        self.assertIn('/load/a', self.model.selection)
        self.assertNotIn('/load/s1', self.model.selection)
        self.assertNotIn('/show_root', self.model.selection)

    def test_hiding_takes_hidden_children_out_of_the_selection(self):
        self.model.set_selection(['/load/a', '/load/s1'])
        self.hide('show')
        self.assertEqual(['/load/a'], list(self.model.selection))

    def test_framing_a_hidden_child_stays_put_and_says_why(self):
        self.hide('show')
        with mock.patch.object(self.view, 'frame_rect') as frame_rect:
            self.view.frame_nodes(['/load/s1'])
        frame_rect.assert_not_called()
        self.assertIn('/load/s1', self.view.status_label.text())

    def test_a_node_made_under_a_shown_node_on_a_hidden_layer(self):
        # It would be hidden as it was made, so the layer shows again.
        self.model.set_target_layer(self.layers['show'])
        self.addCleanup(app.processEvents)
        self.addCleanup(self.model.set_target_layer,
                        self.model.top_layer.real_path)
        self.addCleanup(self.undo_all)
        self.hide('show')
        self.model.add_node(name='more', parent_path='/load',
                            layer=self.model.target_layer)
        app.processEvents()
        self.assertFalse(self.model.get_layer_hidden(self.layers['show']))
        self.assert_shown('/load/more')


class RememberingHiddenLayers(unittest.TestCase):
    """What is remembered stays right as layers come and go, as the graph
    is saved to a new file and with the graph open twice."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_layer_eye_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        key = user_dir.EDITOR_CACHE.HIDDEN_LAYERS
        before = user_dir.editor_cache.get(key) or {}
        self.addCleanup(user_dir.editor_cache.__setitem__, key, before)
        user_dir.editor_cache[key] = {}
        write(os.path.join(self.tmp, 'library.nxt'), {
            'version': '1.17', 'alias': 'library', 'references': [],
            'nodes': {'/template': {}}})
        self.top = write(os.path.join(self.tmp, 'top.nxt'), {
            'version': '1.17', 'alias': 'top', 'references': ['library.nxt'],
            'nodes': {'/made': {'instance': '/template'}}})

    def open(self):
        model = stage_model.StageModel(Session().load_file(self.top))
        model.hidden_layer_paths()
        return model

    @staticmethod
    def stored():
        return user_dir.editor_cache[user_dir.EDITOR_CACHE.HIDDEN_LAYERS]

    def test_a_removed_reference_is_forgotten(self):
        model = self.open()
        library = model.stage._sub_layers[1]
        model.set_layer_hidden(library.real_path)
        changes = []
        model.layer_visibility_changed.connect(lambda: changes.append(1))
        model.remove_sublayer(library)
        self.assertFalse(model.hidden_layer_paths())
        self.assertNotIn(model.top_layer.real_path, self.stored())
        self.assertTrue(changes)

    def test_two_tabs_on_one_graph_keep_each_others_layers(self):
        first, second = self.open(), self.open()
        library = first.stage._sub_layers[1].real_path
        top = first.top_layer.real_path
        first.set_layer_hidden(library)
        second.set_layer_hidden(top)
        self.assertEqual(sorted([library, top]), self.stored()[top])
        second.set_layer_hidden(top, False)
        self.assertEqual([library], self.stored()[top])

    def save_as(self, model, name):
        new_path = os.path.join(self.tmp, name)
        model.top_layer.save(filepath=new_path)
        model.layer_saved.emit(model.top_layer.real_path)
        return model.top_layer.real_path

    def test_saved_to_a_new_file_what_was_hidden_stays_hidden(self):
        model = self.open()
        library = model.stage._sub_layers[1].real_path
        model.set_layer_hidden(library)
        new_path = self.save_as(model, 'saved_as.nxt')
        self.assertTrue(model.get_layer_hidden(library))
        self.assertEqual([library], self.stored()[new_path])

    def test_saved_over_a_file_what_was_remembered_for_it_is_read(self):
        model = self.open()
        library = model.stage._sub_layers[1].real_path
        new_path = os.path.realpath(os.path.join(self.tmp, 'other.nxt'))
        self.stored()[new_path] = [library]
        changes = []
        model.layer_visibility_changed.connect(lambda: changes.append(1))
        self.save_as(model, 'other.nxt')
        self.assertTrue(model.get_layer_hidden(library))
        self.assertTrue(changes)


class ManyRoots(unittest.TestCase):
    """Which nodes are hidden is worked out in one pass. Asking each root
    in turn scanned every layer for every root, and a graph of 2500 took
    more than a second and a half each time the graph changed."""

    COUNT = 2500

    def test_many_roots_are_quick(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_layer_eye_'))
        self.addCleanup(shutil.rmtree, tmp, True)
        key = user_dir.EDITOR_CACHE.HIDDEN_LAYERS
        before = user_dir.editor_cache.get(key) or {}
        self.addCleanup(user_dir.editor_cache.__setitem__, key, before)
        library_nodes = {}
        for index in range(self.COUNT):
            library_nodes['/lib{}'.format(index)] = {}
            library_nodes['/lib{}/child'.format(index)] = {}
        write(os.path.join(tmp, 'library.nxt'), {
            'version': '1.17', 'alias': 'library', 'references': [],
            'nodes': library_nodes})
        top_nodes = dict(('/top{}'.format(index), {})
                         for index in range(self.COUNT))
        # One the top layer adds to, which stays in view.
        top_nodes['/lib0/mine'] = {}
        top = write(os.path.join(tmp, 'top.nxt'), {
            'version': '1.17', 'alias': 'top', 'references': ['library.nxt'],
            'nodes': top_nodes})
        model = stage_model.StageModel(Session().load_file(top))
        model.set_layer_hidden(model.stage._sub_layers[1].real_path)
        start = time.time()
        hidden_nodes = model.hidden_nodes()
        took = time.time() - start
        # Every library node but /lib0, which the top layer adds to. Its
        # own child is the library's alone, so that goes too.
        self.assertEqual(self.COUNT * 2 - 1, len(hidden_nodes))
        self.assertNotIn('/lib0', hidden_nodes)
        self.assertNotIn('/lib0/mine', hidden_nodes)
        self.assertIn('/lib0/child', hidden_nodes)
        self.assertNotIn('/top0', hidden_nodes)
        self.assertLess(took, 0.5)


if __name__ == '__main__':
    unittest.main()
