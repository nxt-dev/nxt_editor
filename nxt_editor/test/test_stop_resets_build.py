"""Stopping a build puts the build view back the way it was.

Stopping while a stepped node was still running ended the build there and
then, with the node carrying on underneath. The build view went back to its
start point, and when the node finished the step ended the build a second
time, which emptied the build list. Inside a host such as Maya, a node runs
on the main thread and Stop is only seen once it is done, so the next node
ran as well before the build stopped.

Each test presses Stop while a node is running, both the way nodes run
standalone (in a thread) and the way they run in a host.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt_editor.dockwidgets.build_view import STARTS
from nxt_editor.main_window import MainWindow

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

NODES = ('/a', '/b', '/c')


def write_graph(folder):
    """Three nodes that each note they ran and then take a moment."""
    ran = os.path.join(folder, 'ran.txt').replace('\\', '/')
    nodes = {}
    previous = None
    for path in NODES:
        code = ['import time',
                'with open("{}", "a") as fp:'.format(ran),
                '    fp.write("{}\\n")'.format(path),
                'time.sleep(0.4)']
        node = {'code': code}
        if previous:
            node['execute_in'] = previous
        else:
            node['start_point'] = True
        nodes[path] = node
        previous = path
    graph = os.path.join(folder, 'graph.nxt')
    with open(graph, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'stop', 'nodes': nodes}, fp)
    return graph, ran


class StopResetsTheBuild(unittest.TestCase):

    hosted = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_stop_')
        graph, self.ran_file = write_graph(self.tmp)
        self.win = MainWindow(filepath=graph)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.model.is_standalone = not self.hosted
        self.view = self.win.build_view
        self.at_stop = None

    def tearDown(self):
        self.win.close()
        app.processEvents()
        self.win.deleteLater()
        app.processEvents()
        self.win = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ran(self):
        if not os.path.isfile(self.ran_file):
            return []
        with open(self.ran_file) as fp:
            return fp.read().split()

    def rows(self):
        return list(self.view.build_model.nodes or [])

    def stop_soon(self):
        """Press Stop while the first node is running."""
        def stop():
            self.at_stop = (self.model.executing,
                            self.view.starts_combo.currentText())
            self.view.stop_button.pressed.emit()
        QtCore.QTimer.singleShot(150, stop)

    def settle(self):
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)

    def assert_put_back(self, start, rows):
        self.assertFalse(self.model.executing, 'still says it is running')
        self.assertFalse(self.view.in_running_mode)
        self.assertEqual(start, self.view.starts_combo.currentText(),
                         'the start box was not put back')
        self.assertEqual(rows, self.rows(), 'the build list was not put back')
        self.assertTrue(self.view.starts_combo.isEnabled())
        self.assertFalse(self.view.stop_button.isEnabled())

    def test_stopping_a_run(self):
        self.assertEqual('/a', self.view.starts_combo.currentText())
        self.stop_soon()
        self.view.exec_build_pressed()
        self.settle()
        self.assertEqual((True, STARTS.RUNNING), self.at_stop)
        self.assertEqual(['/a'], self.ran(),
                         'nodes ran after Stop was pressed')
        self.assert_put_back('/a', list(NODES))

    def test_stopping_a_step(self):
        self.stop_soon()
        self.view.step_build_pressed()
        self.settle()
        self.assertEqual((True, STARTS.RUNNING), self.at_stop)
        self.assertEqual(['/a'], self.ran())
        self.assert_put_back('/a', list(NODES))

    def test_stopping_a_selection_build(self):
        self.model.selection = ['/b', '/c']
        self.view.starts_combo.setEditText(STARTS.SELECTION)
        app.processEvents()
        self.assertEqual(['/b', '/c'], self.rows())
        self.stop_soon()
        self.view.exec_build_pressed()
        self.settle()
        self.assertEqual(['/b'], self.ran())
        self.assert_put_back(STARTS.SELECTION, ['/b', '/c'])

    def test_stopping_when_paused(self):
        self.view.step_build_pressed()
        self.assertTrue(self.model.build_paused)
        self.view.stop_button.pressed.emit()
        self.settle()
        self.assertEqual(['/a'], self.ran())
        self.assert_put_back('/a', list(NODES))

    def test_pressing_stop_again_changes_nothing(self):
        self.stop_soon()
        self.view.exec_build_pressed()
        self.settle()
        self.view.stop_button.pressed.emit()
        self.model.stop_build()
        self.settle()
        self.assert_put_back('/a', list(NODES))

    def test_another_build_after_stopping(self):
        self.stop_soon()
        self.view.exec_build_pressed()
        self.settle()
        self.view.exec_build_pressed()
        self.settle()
        self.assertEqual(['/a'] + list(NODES), self.ran())
        self.assert_put_back('/a', list(NODES))


class StopResetsTheBuildInAHost(StopResetsTheBuild):

    hosted = True


if __name__ == '__main__':
    unittest.main()
