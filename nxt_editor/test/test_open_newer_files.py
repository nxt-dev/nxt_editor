"""A graph saved by a newer nxt can be opened anyway, after a warning.

Opening one, or one that references one, used to refuse outright. The
editor now asks, saying the version, and opens it if told to.
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

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt import nxt_io  # noqa: E402
from nxt.constants import GRAPH_VERSION  # noqa: E402
from nxt_editor import main_window  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402

NEWER = '{}.{}'.format(GRAPH_VERSION.MAJOR, GRAPH_VERSION.MINOR + 1)
NEEDS_CORE = 'needs an nxt_core that can open newer files'


def write_graph(path, alias, version='1.17', references=()):
    with open(path, 'w') as file_object:
        json.dump({'version': version, 'alias': alias,
                   'references': list(references),
                   'nodes': {'/' + alias: {}}}, file_object)
    return path


@unittest.skipUnless(hasattr(nxt_io, 'allow_newer_files'), NEEDS_CORE)
class OpeningNewerFiles(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_newer_ui_'))
        self.newer = write_graph(os.path.join(self.tmp, 'newer.nxt'),
                                 'newer', NEWER)
        self.top = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                               references=['newer.nxt'])
        self.win = MainWindow()
        app.processEvents()

    def tearDown(self):
        message = self.win.missing_references_message
        if message is not None:
            message.close()
        self.win.hide()
        app.processEvents()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, path, answer):
        self.tabs_before = len(self.win.open_files)
        self.loaded_before = len(self.win.nxt.loaded_files)
        with mock.patch.object(main_window.NxtConfirmDialog, 'show_message',
                               return_value=answer) as ask, \
                mock.patch.object(main_window.NxtWarningDialog,
                                  'show_message') as warn:
            self.win.load_file(path)
        app.processEvents()
        return ask, warn

    def aliases(self):
        if not self.win.model:
            return []
        return [l.get_alias() for l in self.win.model.stage._sub_layers]

    def test_it_asks_saying_the_version(self):
        ask, warn = self.open(self.newer, False)
        ask.assert_called_once()
        self.assertIn(NEWER, ask.call_args.kwargs['text'])
        warn.assert_not_called()

    def test_declining_opens_nothing(self):
        self.open(self.newer, False)
        self.assertEqual(self.tabs_before, len(self.win.open_files))

    def test_open_anyway(self):
        self.open(self.newer, True)
        self.assertEqual(['newer'], self.aliases())

    def test_a_newer_reference_is_asked_about(self):
        ask, _ = self.open(self.top, True)
        ask.assert_called_once()
        self.assertIn('newer.nxt', ask.call_args.kwargs['text'])
        self.assertEqual(['top', 'newer'], self.aliases())
        # Opened once, not once with the reference and once without.
        self.assertEqual(self.tabs_before + 1, len(self.win.open_files))
        self.assertEqual(self.loaded_before + 1,
                         len(self.win.nxt.loaded_files))

    def test_declining_a_newer_reference_opens_without_it(self):
        self.open(self.top, False)
        self.assertEqual(['top'], self.aliases())

    def test_nothing_is_asked_for_a_current_graph(self):
        current = write_graph(os.path.join(self.tmp, 'current.nxt'), 'cur')
        ask, _ = self.open(current, True)
        ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
