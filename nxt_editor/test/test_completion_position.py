"""The completion list opens under the word being completed.

Its names start where the word starts, so a row reads on from what is
typed, and it sits under the line rather than over the bottom of it.
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
from Qt import QtGui, QtWidgets

# Internal
from nxt import DATA_STATE

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class CompletionPosition(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='nxt_completion_position_')
        graph = os.path.join(cls.tmp, 'position.nxt')
        with open(graph, 'w') as fp:
            json.dump({'version': '1.17', 'alias': 'position',
                       'nodes': {'/node': {'code': ['']}}}, fp)
        cls.win = MainWindow(filepath=graph)
        cls.editor = cls.win.code_editor.editor
        cls.win.model.data_state = DATA_STATE.RAW
        cls.win.model.set_selection(['/node'])
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self, text):
        self.editor.setReadOnly(False)
        # A window that is not shown is a few characters wide, and a word
        # that wraps or starts out of view is another case.
        self.editor.resize(900, 300)
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(cursor)
        app.processEvents()

    def rect_at(self, characters_back):
        """The cursor's rect that many characters before the end, in the
        code editor's own coordinates."""
        cursor = self.editor.textCursor()
        cursor.setPosition(cursor.position() - characters_back)
        rect = self.editor.cursorRect(cursor)
        rect.translate(self.editor.viewport().pos())
        return rect

    def test_the_line_numbers_do_not_push_it_left(self):
        self.load('import os\nresult = os.pa')
        self.assertGreater(self.editor.viewport().x(), 0)
        rect = self.editor.completion_rect('pa')
        self.assertLess(self.rect_at(2).left() - rect.left(), 8)
        self.assertGreaterEqual(self.rect_at(2).left(), rect.left())

    def test_it_opens_under_the_line(self):
        self.load('result = os.pa')
        rect = self.editor.completion_rect('os.pa')
        self.assertEqual(rect.bottom(), self.rect_at(0).bottom())

    def test_it_starts_where_the_word_starts(self):
        self.load('    result = STAGE.rig.bu')
        rect = self.editor.completion_rect('STAGE.rig.bu')
        word_start = self.rect_at(len('STAGE.rig.bu')).left()
        self.assertLess(rect.left(), self.rect_at(0).left())
        self.assertLess(abs(word_start - rect.left()), 8)

    def test_a_word_at_the_start_of_a_line_stays_in_the_text(self):
        self.load('STA')
        rect = self.editor.completion_rect('STA')
        self.assertGreaterEqual(rect.left(), self.editor.viewport().x())

    def test_the_list_is_put_up_there(self):
        self.load('result = os.pa')
        self.editor.completer.model().setStringList(['os.path', 'os.pardir'])
        with mock.patch.object(self.editor.completer, 'complete') as complete:
            self.editor.show_completions('os.pa')
        self.assertEqual(complete.call_args[0][0],
                         self.editor.completion_rect('os.pa'))
        self.editor.set_completion_shortcuts(True)


if __name__ == '__main__':
    unittest.main()
