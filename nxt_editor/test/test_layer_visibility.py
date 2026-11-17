"""A layer can be hidden in the graph without being taken out of it.

A library layer of nodes that are only there to be instanced fills the
graph of every layer above it. Muting it is not an answer, the graph needs
it to build. The eye in the Layer Manager hides what only that layer has:
its root nodes and everything under them, the lines to and from them, and
its backdrops. The comp does not change, so the graph builds the same.

It is a view, kept per user and per graph in the editor's cache. It never
marks a layer unsaved.
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
from Qt import QtCore, QtTest, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model, user_dir
from nxt_editor.dockwidgets.layer_manager import LayerModel

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


if __name__ == '__main__':
    unittest.main()
