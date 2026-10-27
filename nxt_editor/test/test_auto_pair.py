"""Typing an opening bracket or quote in the code editor closes it too.

The closer goes in after the cursor, a closer that is already there is
stepped over rather than doubled, and a selection is wrapped. Quotes are
left alone next to a word, where they are apostrophes or string prefixes,
and as the third quote of a triple quote.

The keys are handed to the editor's own key handler, the way Qt hands
them over, so these do not depend on which window has focus.
"""
# Builtin
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

KEYS = {'(': QtCore.Qt.Key_ParenLeft, ')': QtCore.Qt.Key_ParenRight,
        '[': QtCore.Qt.Key_BracketLeft, ']': QtCore.Qt.Key_BracketRight,
        '{': QtCore.Qt.Key_BraceLeft, '}': QtCore.Qt.Key_BraceRight,
        '"': QtCore.Qt.Key_QuoteDbl, "'": QtCore.Qt.Key_Apostrophe,
        '$': QtCore.Qt.Key_Dollar}


class AutoPair(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.win = MainWindow()
        cls.win.resize(1400, 900)
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def load(self, text, position=None, anchor=None):
        """Editable text, with the cursor, or a selection, where asked."""
        self.editor.setReadOnly(False)
        self.ce.editing_active = True
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        if anchor is not None:
            cursor.setPosition(anchor)
            cursor.setPosition(position, QtGui.QTextCursor.KeepAnchor)
        else:
            cursor.setPosition(len(text) if position is None else position)
        self.editor.setTextCursor(cursor)

    def type(self, text, modifiers=QtCore.Qt.NoModifier):
        for char in text:
            key = KEYS.get(char) or QtGui.QKeySequence(char)[0].key()
            event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, modifiers,
                                    char)
            self.editor.keyPressEvent(event)

    def shown(self):
        """The text with a | where the cursor is."""
        text = self.editor.toPlainText()
        position = self.editor.textCursor().position()
        return text[:position] + '|' + text[position:]

    def test_an_opener_brings_its_closer(self):
        for opener, closer in (('(', ')'), ('[', ']'), ('{', '}'),
                               ('"', '"'), ("'", "'")):
            self.load('')
            self.type(opener)
            self.assertEqual(opener + '|' + closer, self.shown())

    def test_a_closer_already_there_is_stepped_over(self):
        self.load('')
        self.type('()')
        self.assertEqual('()|', self.shown())

    def test_a_selection_is_wrapped_and_stays_selected(self):
        for opener, closer in (('(', ')'), ('"', '"'), ("'", "'")):
            self.load('word', position=4, anchor=0)
            self.type(opener)
            self.assertEqual(opener + 'word' + closer,
                             self.editor.toPlainText())
            self.assertEqual('word',
                             self.editor.textCursor().selectedText())

    def test_a_selection_made_backwards_is_wrapped_too(self):
        self.load('word', position=0, anchor=4)
        self.type('"')
        self.assertEqual('"word"', self.editor.toPlainText())

    def test_a_triple_quote_stays_three_quotes(self):
        self.load('')
        self.type('"""')
        self.assertEqual('"""|', self.shown())

    def test_an_apostrophe_in_a_word_is_just_typed(self):
        self.load('it')
        self.type("'")
        self.assertEqual("it'|", self.shown())

    def test_altgr_typing_a_bracket_still_pairs(self):
        # AltGr arrives as Ctrl+Alt on Windows, and is how [ and { are
        # typed on many keyboard layouts.
        self.load('')
        self.type('[', QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
        self.assertEqual('[|]', self.shown())

    def test_ctrl_with_a_bracket_is_not_typing(self):
        self.load('')
        self.type('[', QtCore.Qt.ControlModifier)
        self.assertEqual('|', self.shown())

    def test_nothing_is_paired_while_read_only(self):
        self.load('')
        self.editor.setReadOnly(True)
        self.ce.editing_active = False
        self.type('(')
        self.assertEqual('', self.editor.toPlainText())

    def test_a_token_completion_does_not_leave_a_spare_brace(self):
        # ${ pairs a } that the completion brings its own of.
        self.load('')
        self.type('${')
        self.assertEqual('${|}', self.shown())
        self.type('va')
        self.editor.insert_completion('${value}')
        self.assertEqual('${value}|', self.shown())


if __name__ == '__main__':
    unittest.main()
