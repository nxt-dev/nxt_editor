"""Opening a graph with references that cannot be found says so, and offers
the Reference Editor to point them at the right files.

The references are kept as written, so a graph opened on a machine that
lacks one does not lose it. Nothing said so except a line in the log.
The notice is not modal: a script opening graphs is not held up by it.
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
from nxt_editor.dialogs import MissingReferencesMessage  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402


def write_graph(path, alias, references=()):
    with open(path, 'w') as file_object:
        json.dump({'version': '1.17', 'alias': alias,
                   'references': list(references),
                   'nodes': {'/' + alias: {}}}, file_object)
    return path


class MissingReferencesNotice(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_missing_'))
        write_graph(os.path.join(self.tmp, 'mid.nxt'), 'mid',
                    ['gone_too.nxt'])
        write_graph(os.path.join(self.tmp, 'beside.nxt'), 'beside')
        self.top = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                               ['mid.nxt', 'beside.nxt', 'gone.nxt'])
        self.whole = write_graph(os.path.join(self.tmp, 'whole.nxt'),
                                 'whole', ['beside.nxt'])
        self.win = MainWindow()
        self.win.show()
        app.processEvents()

    def tearDown(self):
        message = self.win.missing_references_message
        if message is not None:
            message.close()
        self.win.hide()
        app.processEvents()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, path):
        self.win.load_file(path)
        app.processEvents()
        return self.win.missing_references_message

    def test_the_model_lists_them_by_layer(self):
        self.open(self.top)
        missing = [(layer.get_alias(), refs)
                   for layer, refs in self.win.model.missing_references()]
        self.assertEqual([('top', ['gone.nxt']), ('mid', ['gone_too.nxt'])],
                         missing)

    def test_opening_says_so_without_waiting(self):
        message = self.open(self.top)
        self.assertIsInstance(message, MissingReferencesMessage)
        self.assertTrue(message.isVisible())
        self.assertFalse(message.isModal())
        self.assertIn('2 references', message.text())
        details = message.detailedText()
        self.assertIn('gone.nxt', details)
        self.assertIn('gone_too.nxt', details)

    def test_edit_opens_the_reference_editor_on_the_layer(self):
        message = self.open(self.top)
        with mock.patch.object(main_window, 'ReferenceEditor') as editor:
            editor.return_value.exec_.return_value = 0
            message.edit_button.click()
            app.processEvents()
        editor.assert_called_once()
        model = editor.call_args.args[0]
        self.assertIs(self.win.model, model)
        self.assertEqual(model.top_layer.real_path,
                         editor.call_args.kwargs['layer_path'])

    def test_ignore_just_closes_it(self):
        message = self.open(self.top)
        with mock.patch.object(main_window, 'ReferenceEditor') as editor:
            ignore = [b for b in message.buttons() if b.text() == 'Ignore']
            ignore[0].click()
            app.processEvents()
        editor.assert_not_called()
        self.assertFalse(message.isVisible())

    def test_a_graph_with_everything_found_says_nothing(self):
        self.assertIsNone(self.open(self.whole))


if __name__ == '__main__':
    unittest.main()
