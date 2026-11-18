"""Each step of a build redraws only the nodes whose look changes.

Every node hears about every step, to know whether it is the one running.
Each redrew itself whether that changed or not, so a build of n nodes drew
n * n of them, and in a host, which runs nodes on the thread that draws,
the host stood still for it.
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
from nxt_editor.main_window import MainWindow
from nxt_editor.node_graphics_item import NodeGraphicsItem

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

COUNT = 20


def write_graph(folder):
    nodes = {}
    previous = None
    for i in range(COUNT):
        node = {'code': ['x = {}'.format(i)]}
        if previous:
            node['execute_in'] = previous
        else:
            node['start_point'] = True
        previous = '/n{}'.format(i)
        nodes[previous] = node
    graph = os.path.join(folder, 'graph.nxt')
    with open(graph, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'many', 'nodes': nodes}, fp)
    return graph


class BuildRedrawsFewNodes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_build_redraw_')
        self.win = MainWindow(filepath=write_graph(self.tmp))
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        # Run on this thread, the way a host runs nodes.
        self.model.is_standalone = False

    def tearDown(self):
        self.win.hide()
        app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_build_redraws_each_node_a_few_times(self):
        per_node = {}
        original = NodeGraphicsItem.update

        def update(item, *args):
            per_node[item.node_path] = per_node.get(item.node_path, 0) + 1
            return original(item, *args)
        with mock.patch.object(NodeGraphicsItem, 'update', update):
            self.win.build_view.exec_build_pressed()
            app.processEvents()
        self.assertFalse(self.model.executing)
        # On when it starts running, off when the next one does, and once
        # when the build starts or ends. It was COUNT times each.
        self.assertEqual(COUNT, len(per_node))
        self.assertLessEqual(max(per_node.values()), 4)

    def test_the_running_node_is_still_drawn_as_running(self):
        self.win.build_view.step_build_pressed()
        app.processEvents()
        view = self.win.view
        items = {i.node_path: i for i in view.scene().items()
                 if isinstance(i, NodeGraphicsItem)}
        running = self.model.get_build_focus()
        self.assertTrue(running)
        self.assertEqual([running],
                         [p for p, i in items.items() if i.is_build_focus])
        self.model.stop_build()
        app.processEvents()
        self.assertFalse(any(i.is_build_focus for i in items.values()))


if __name__ == '__main__':
    unittest.main()
