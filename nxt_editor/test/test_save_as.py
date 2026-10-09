"""Save As into another folder keeps the copy's references working, and
leaves the original as it was.

The copy opens in a new tab while the old tab keeps the original, so the
save writes a copy: the copy's relative references are written again from
its new folder, and the original's are not touched, in memory or on disk.
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

from nxt_editor import main_window  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402


def write_graph(path, alias, references=()):
    with open(path, 'w') as file_object:
        json.dump({'version': '1.17', 'alias': alias,
                   'references': list(references),
                   'nodes': {'/' + alias: {}}}, file_object)
    return path


class SaveAsElsewhere(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_save_as_ui_')
        self.graph_dir = os.path.join(self.tmp, 'graph')
        self.copy_dir = os.path.join(self.tmp, 'copy')
        os.makedirs(self.graph_dir)
        os.makedirs(self.copy_dir)
        self.beside = write_graph(os.path.join(self.graph_dir, 'beside.nxt'),
                                  'beside')
        self.top = write_graph(os.path.join(self.graph_dir, 'top.nxt'), 'top',
                               ['beside.nxt'])
        self.copy = os.path.join(self.copy_dir, 'top_copy.nxt')
        self.win = MainWindow(filepath=self.top)
        app.processEvents()

    def tearDown(self):
        self.win.hide()
        app.processEvents()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save_as(self):
        layer = self.win.model.top_layer
        with mock.patch.object(main_window.NxtFileDialog,
                               'system_file_dialog',
                               return_value=self.copy):
            self.assertTrue(self.win.save_layer_as(layer))
        app.processEvents()
        return layer

    def test_the_copy_finds_its_reference(self):
        self.save_as()
        with open(self.copy) as file_object:
            data = json.load(file_object)
        self.assertEqual([self.beside.replace(os.sep, '/')],
                         data['references'])

    def test_the_original_is_left_as_it_was(self):
        layer = self.save_as()
        self.assertEqual(['beside.nxt'], layer.get_references())
        self.assertEqual(os.path.normcase(self.top),
                         os.path.normcase(layer.real_path))
        layer.save()
        with open(self.top) as file_object:
            self.assertEqual(['beside.nxt'],
                             json.load(file_object)['references'])


if __name__ == '__main__':
    unittest.main()
