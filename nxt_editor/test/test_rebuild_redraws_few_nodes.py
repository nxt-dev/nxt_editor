"""Building the comp again draws again only the nodes that changed.

Every node was drawn again after an edit that builds the comp again, as
moving a node to another parent does. For a graph of ten thousand nodes
that took most of a minute, for an edit that changed a handful.
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
from Qt import QtWidgets

# Internal
from nxt import nxt_layer
from nxt_editor.main_window import MainWindow
from nxt_editor.node_graphics_item import NodeGraphicsItem

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

COUNT = 20


def write_graph(folder):
    nodes = {'/n{}'.format(i): {} for i in range(COUNT)}
    nodes['/src'] = {'attrs': {'v': {'value': 'x'}}}
    nodes['/inst'] = {'instance': '/src'}
    graph = os.path.join(folder, 'graph.nxt')
    with open(graph, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'many', 'nodes': nodes}, fp)
    return graph


@unittest.skipUnless(hasattr(nxt_layer, 'changed_nodes'),
                     'nxt core without changed_nodes')
class RebuildRedrawsFewNodes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_rebuild_redraw_')
        self.win = MainWindow(filepath=write_graph(self.tmp))
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.view = self.win.view

    def tearDown(self):
        self.win.hide()
        app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def drawn_again(self, rebuild):
        drawn = []
        original = NodeGraphicsItem.update_from_model

        def update_from_model(item, *args, **kwargs):
            drawn.append(item.node_path)
            return original(item, *args, **kwargs)
        with mock.patch.object(NodeGraphicsItem, 'update_from_model',
                               update_from_model):
            rebuild()
            app.processEvents()
        return set(drawn)

    def test_nothing_changed_nothing_drawn(self):
        drawn = self.drawn_again(
            lambda: self.model.update_comp_layer(rebuild=True))
        self.assertEqual(set(), drawn)
        self.assertEqual(COUNT + 2, len([
            p for p in self.view._node_graphics]))

    def test_a_changed_node_and_its_instance_are_drawn(self):
        layer = self.model.stage.top_layer
        self.model.stage.node_setattr_data(layer.lookup('/src'), 'v', layer,
                                           create=False, value='y')
        drawn = self.drawn_again(
            lambda: self.model.update_comp_layer(rebuild=True))
        self.assertEqual({'/src', '/inst'}, drawn)

    def test_a_moved_node_is_drawn_where_it_went(self):
        self.model.parent_nodes(['/n1'], '/n0')
        app.processEvents()
        self.assertIn('/n0/n1', self.view._node_graphics)
        self.assertNotIn('/n1', self.view._node_graphics)
        self.assertTrue(self.model.comp_is_exact)


if __name__ == '__main__':
    unittest.main()
