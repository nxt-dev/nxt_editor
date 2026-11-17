"""Ignore Breakpoints lets a run go through every breakpoint without taking
any of them off.

It is a checkable action in the Execute menu and on the execute toolbar,
remembered as a user pref, and it is read as a run goes, so turning it on
while a build is paused at a breakpoint lets the rest of the run through.
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
from Qt import QtWidgets

# Internal
from nxt_editor import user_dir
from nxt_editor.main_window import MainWindow

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

NODES = ('/a', '/b', '/c')
PREF = user_dir.USER_PREF.IGNORE_BREAKS


def write_graph(folder):
    """Three nodes in a chain that each note they ran."""
    ran = os.path.join(folder, 'ran.txt').replace('\\', '/')
    nodes = {}
    previous = None
    for path in NODES:
        code = ['with open("{}", "a") as fp:'.format(ran),
                '    fp.write("{}\\n")'.format(path)]
        node = {'code': code}
        if previous:
            node['execute_in'] = previous
        else:
            node['start_point'] = True
        nodes[path] = node
        previous = path
    graph = os.path.join(folder, 'graph.nxt')
    with open(graph, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'breaks', 'nodes': nodes}, fp)
    return graph, ran


class IgnoreBreakpoints(unittest.TestCase):

    def setUp(self):
        user_dir.user_prefs[PREF] = False
        self.tmp = tempfile.mkdtemp(prefix='nxt_ignore_breaks_')
        graph, self.ran_file = write_graph(self.tmp)
        self.win = MainWindow(filepath=graph)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        # Run on this thread, the way a host runs nodes.
        self.model.is_standalone = False
        self.action = self.win.execute_actions.ignore_breaks_action
        self.action.setChecked(False)
        self.model.set_breakpoints(['/b'], True)

    def tearDown(self):
        user_dir.user_prefs[PREF] = False
        self.win.hide()
        app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ran(self):
        if not os.path.isfile(self.ran_file):
            return []
        with open(self.ran_file) as fp:
            return fp.read().split()

    def settle(self):
        for _ in range(10):
            app.processEvents()
            time.sleep(0.02)

    def run_build(self):
        self.win.build_view.exec_build_pressed()
        self.settle()

    def test_a_breakpoint_stops_the_run_by_default(self):
        self.run_build()
        self.assertEqual(['/a'], self.ran())
        self.assertTrue(self.model.build_paused)

    def test_ignored_breakpoints_are_run_through(self):
        self.action.trigger()
        self.assertTrue(self.action.isChecked())
        self.run_build()
        self.assertEqual(list(NODES), self.ran())
        self.assertFalse(self.model.build_paused)
        # The breakpoint is still there.
        self.assertEqual(['/b'], self.model.get_breakpoints())

    def test_turning_it_on_while_paused_lets_the_rest_run(self):
        self.run_build()
        self.assertEqual(['/a'], self.ran())
        self.model.set_breakpoints(['/c'], True)
        self.action.trigger()
        self.model.resume_build()
        self.settle()
        self.assertEqual(list(NODES), self.ran())

    def test_it_is_remembered_as_a_pref(self):
        self.action.trigger()
        self.assertTrue(user_dir.user_prefs.get(PREF))
        self.assertTrue(self.model.breakpoints_ignored())
        self.action.trigger()
        self.assertFalse(user_dir.user_prefs.get(PREF))
        self.assertFalse(self.model.breakpoints_ignored())

    def test_the_graph_redraws_its_breakpoints(self):
        # Ignored breakpoints are drawn hollow, and nodes cache how they
        # look, so toggling has to tell them.
        seen = []
        self.model.breaks_changed.connect(seen.append)
        self.action.trigger()
        self.assertEqual([('/b',)], [tuple(paths) for paths in seen])

    def test_it_is_in_the_menu_toolbar_and_hotkey_editor(self):
        menu = self.win.menuBar().execute_menu
        self.assertIn(self.action, menu.actions())
        toolbar = self.win.execute_toolbar
        self.assertIn(self.action, toolbar.actions())
        self.assertFalse(self.action.icon().isNull())
        names = [row[0] for row in
                 self.win.execute_actions.get_action_data()]
        self.assertIn('Ignore Breakpoints', names)


if __name__ == '__main__':
    unittest.main()
