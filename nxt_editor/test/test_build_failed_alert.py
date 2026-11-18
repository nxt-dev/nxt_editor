"""A build that fails dings and, when the editor is not in front, flashes
it, so a long build that stopped is noticed without going back to look.

The ding is the editor's error sound, which the Options menu turns off.
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
from nxt_editor import user_dir
from nxt_editor.main_window import MainWindow

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(folder, fail):
    code = ['undefined_name'] if fail else ['x = 1']
    nodes = {'/a': {'start_point': True, 'code': ['x = 0']},
             '/b': {'execute_in': '/a', 'code': code}}
    graph = os.path.join(folder, 'graph.nxt')
    with open(graph, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'fails', 'nodes': nodes}, fp)
    return graph


class BuildFailedAlert(unittest.TestCase):

    fail = True

    def setUp(self):
        user_dir.user_prefs[user_dir.USER_PREF.DING] = True
        self.tmp = tempfile.mkdtemp(prefix='nxt_build_failed_')
        self.win = MainWindow(filepath=write_graph(self.tmp, self.fail))
        self.win.show()
        app.processEvents()
        # Run on this thread, the way a host runs nodes.
        self.win.model.is_standalone = False
        self.failed = []
        self.win.model.build_failed.connect(self.failed.append)

    def tearDown(self):
        user_dir.user_prefs[user_dir.USER_PREF.DING] = True
        self.win.hide()
        app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_build(self, active):
        with mock.patch.object(QtWidgets.QApplication, 'beep') as beep, \
                mock.patch.object(QtWidgets.QApplication, 'alert') as alert, \
                mock.patch.object(self.win, 'isActiveWindow',
                                  return_value=active):
            self.win.build_view.exec_build_pressed()
            app.processEvents()
        return beep, alert


class AFailingBuild(BuildFailedAlert):

    def test_it_says_which_node_failed(self):
        self.run_build(active=True)
        self.assertEqual(['/b'], self.failed)

    def test_it_dings(self):
        beep, _ = self.run_build(active=True)
        beep.assert_called_once()

    def test_it_flashes_the_window_when_not_in_front(self):
        _, alert = self.run_build(active=False)
        alert.assert_called_once_with(self.win, 0)

    def test_it_does_not_flash_the_window_in_front(self):
        _, alert = self.run_build(active=True)
        alert.assert_not_called()

    def test_the_error_sound_can_be_turned_off(self):
        user_dir.user_prefs[user_dir.USER_PREF.DING] = False
        beep, alert = self.run_build(active=False)
        beep.assert_not_called()
        alert.assert_called_once()


class ABuildThatWorks(BuildFailedAlert):

    fail = False

    def test_it_is_quiet(self):
        beep, alert = self.run_build(active=False)
        self.assertEqual([], self.failed)
        beep.assert_not_called()
        alert.assert_not_called()

    def test_stopping_it_is_quiet(self):
        self.win.model.set_breakpoints(['/b'], True)
        self.win.build_view.exec_build_pressed()
        app.processEvents()
        self.assertTrue(self.win.model.build_paused)
        with mock.patch.object(QtWidgets.QApplication, 'beep') as beep:
            self.win.model.stop_build()
            app.processEvents()
        self.assertEqual([], self.failed)
        beep.assert_not_called()


del BuildFailedAlert

if __name__ == '__main__':
    unittest.main()
