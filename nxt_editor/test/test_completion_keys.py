"""Driving the completion popup from the keyboard.

Qt offers every key to the editor before the completer gets to act on
it, and takes the editor accepting the key as the whole answer. A plain
text edit accepts Return, so pressing it on a highlighted completion put
a new line in the code and the completer never heard about it: the list
went away and the word that was chosen was never written.

The keys the popup needs have to be handed over while it is up. There
are two halves to that: the editor actions bound to Return, Tab and Esc
stand down so the key is not eaten as a shortcut, and the key press
itself is left unaccepted so Qt falls back on the completer.

Most of these ask the editor what it does with a key rather than sending
one through the window system. A popup is a window, and which window a
key lands in depends on what else is on screen, which is not what these
are trying to find out. One test at the end does the whole thing for
real, in a window of its own.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets
try:
    from Qt import QtTest
except ImportError:
    # Maya's PySide6 does not ship it.
    QtTest = None

# Internal
from nxt_editor import user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

SOURCE_PREFS = (
    user_dir.USER_PREF.CE_COMPLETE_PYTHON,
    user_dir.USER_PREF.CE_COMPLETE_MODULES,
    user_dir.USER_PREF.CE_COMPLETE_NODE,
    user_dir.USER_PREF.CE_COMPLETE_DOCUMENT,
)

# Two words sharing a prefix, so there is a list to move around in
# whatever else this machine offers completions from.
CODE = "# printing printable\nprin"

TAKE_IT = (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Tab)
LEAVE_IT = (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Backtab)


def close_window(window):
    """Finish with a window, rather than leaving it to the collector.

    close() only hides it, and dropping the last reference leaves the
    whole widget tree to be freed at whatever unrelated moment something
    else collects. A completion popup that outlives its window segfaults
    when that happens, a long way from the test that made it.
    """
    window.close()
    app.processEvents()
    window.deleteLater()
    app.processEvents()


def key_event(key):
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, QtCore.Qt.NoModifier)


def key_click(widget, key):
    """Press and release a key on a widget.

    QTest where there is one: on macOS the completer only treats a key as
    typed when it arrives the way QTest delivers it. Maya's PySide6 has no
    QtTest, so there the events are sent directly, which is what the
    completer's event filter on the popup sees on Windows and Linux too.
    """
    if QtTest is not None:
        QtTest.QTest.keyClick(widget, key)
        return
    for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
        QtWidgets.QApplication.sendEvent(
            widget, QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier))


def make_active(window):
    """Make a window the active one, so focus can be given inside it.

    Offscreen on macOS a window never becomes active on its own, and
    setFocus() in an inactive window does nothing: the keys then went to
    whatever did have focus, the node graph, where Down moved the
    selection and ended the edit being tested.
    """
    window.activateWindow()
    set_active = getattr(QtWidgets.QApplication, 'setActiveWindow', None)
    if set_active is not None:
        set_active(window)
    app.processEvents()


def give_focus(widget):
    """Focus a widget once its window has finished taking focus back.

    A window that becomes active hands focus to whatever last had it,
    which can arrive after a setFocus() made before it. So ask again
    until it holds, for as long as that takes to settle.
    """
    for _ in range(20):
        widget.setFocus()
        app.processEvents()
        if QtWidgets.QApplication.focusWidget() is widget:
            return


def restore_prefs(saved):
    for key, value in saved.items():
        if value is None:
            # There was no preference before, so leaving ours behind
            # would not be restoring anything.
            try:
                user_dir.user_prefs.pop(key)
            except KeyError:
                pass
            continue
        user_dir.user_prefs[key] = value


def arm(code_editor, text=CODE):
    """Put a completion list up over known text."""
    editor = code_editor.editor
    editor.hide_completions()
    app.processEvents()
    editor.setReadOnly(False)
    code_editor.editing_active = True
    editor.setPlainText(text)
    cursor = editor.textCursor()
    cursor.movePosition(QtGui.QTextCursor.End)
    editor.setTextCursor(cursor)
    editor.invalidate_completion_words()
    editor.update_completions(force=True)
    app.processEvents()


class WhatTheEditorDoesWithAKey(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.win = MainWindow(filepath="StageInstanceTest.nxt")
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.actions = cls.win.code_editor_actions
        cls.ce.stage_model.set_selection(['/inst_source1'])
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.editor.hide_completions()
        cls.ce.stage_model.effected_layers.clear()
        close_window(cls.win)
        cls.win = None

    def setUp(self):
        # These are real preferences on disk. Put back whatever the
        # person running the tests had rather than leaving ours behind.
        self.saved = {k: user_dir.user_prefs.get(k) for k in SOURCE_PREFS}
        for action, _pref, _d in self.actions.completion_source_actions:
            action.setChecked(True)
        arm(self.ce)
        self.assertTrue(self.popup.isVisible(), 'nothing to drive')

    def tearDown(self):
        self.editor.hide_completions()
        app.processEvents()
        restore_prefs(self.saved)

    @property
    def popup(self):
        return self.editor.completer.popup()

    def send(self, key):
        """Hand a key to the editor the way the completer does.

        The completer offers each key to the editor first and reads back
        whether it was accepted, so that is what this asks about.

        :return: the event, to ask whether it was accepted
        """
        event = key_event(key)
        self.editor.keyPressEvent(event)
        return event

    def last_line(self):
        return self.editor.toPlainText().split('\n')[-1]

    # -- there is a list to take something from -------------------------

    def test_the_popup_is_up_with_something_in_it(self):
        self.assertGreater(self.editor.completer.completionCount(), 1,
                           'this test needs a list to move around in')

    # -- the keys the popup needs are handed over -----------------------

    def test_the_keys_that_take_a_completion_are_left_to_it(self):
        for key in TAKE_IT:
            event = self.send(key)
            self.assertFalse(event.isAccepted(),
                             'the editor kept key %s, so the completer '
                             'never heard about it and what was chosen '
                             'was never written' % int(key))

    def test_the_keys_that_dismiss_it_are_left_to_it_as_well(self):
        for key in LEAVE_IT:
            self.assertFalse(self.send(key).isAccepted(), int(key))

    def test_return_writes_nothing_of_its_own(self):
        before = self.editor.toPlainText()
        self.send(QtCore.Qt.Key_Return)
        self.assertEqual(before, self.editor.toPlainText(),
                         'a new line went in where a completion belonged')

    def test_tab_indents_nothing_of_its_own(self):
        before = self.editor.toPlainText()
        self.send(QtCore.Qt.Key_Tab)
        self.assertEqual(before, self.editor.toPlainText())

    def test_an_ordinary_key_is_still_the_editors(self):
        self.send(QtCore.Qt.Key_Down)
        self.assertEqual(CODE, self.editor.toPlainText())

    # -- and a taken key lands somewhere useful -------------------------

    def test_what_the_completer_settles_on_is_written(self):
        # Where a taken key ends up: the completer works out what was
        # chosen and says so, and this is what has to happen then.
        self.editor.insert_completion('printable')
        self.assertEqual('printable', self.last_line())

    def test_writing_one_hands_the_keys_back(self):
        # Return, Tab and Esc are editor actions the rest of the time.
        # They stand down while the popup is up, and a completion that
        # did not hand them back would leave the editor unable to make a
        # new line for the rest of the session.
        self.editor.insert_completion('printable')
        for action in (self.actions.new_line,
                       self.actions.indent_line,
                       self.actions.accept_edit_action,
                       self.actions.cancel_edit_action):
            self.assertTrue(action.isEnabled(), action.text())

    def test_putting_the_list_away_hands_them_back_too(self):
        self.editor.hide_completions()
        for action in (self.actions.new_line,
                       self.actions.indent_line,
                       self.actions.accept_edit_action,
                       self.actions.cancel_edit_action):
            self.assertTrue(action.isEnabled(), action.text())

    # -- with no list up, the editor keeps its keys ---------------------

    def test_return_is_the_editors_again_once_the_list_is_down(self):
        self.editor.hide_completions()
        app.processEvents()
        before = self.editor.toPlainText().count('\n')
        self.editor.keyPressEvent(key_event(QtCore.Qt.Key_Return))
        self.assertGreater(self.editor.toPlainText().count('\n'), before,
                           'the editor stopped being able to make a new '
                           'line when nothing was being completed')


class TakingOneForReal(unittest.TestCase):
    """The whole thing, driven by keys, in a window of its own.

    Worth doing once properly, because what was wrong was the
    arrangement of editor, completer and popup rather than any one of
    them. It gets its own window so that nothing another test left on
    screen can dismiss the popup between it going up and a key arriving.
    """

    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.saved = {k: user_dir.user_prefs.get(k) for k in SOURCE_PREFS}
        self.win = MainWindow(filepath="StageInstanceTest.nxt")
        self.ce = self.win.code_editor
        self.editor = self.ce.editor
        actions = self.win.code_editor_actions
        for action, _pref, _d in actions.completion_source_actions:
            action.setChecked(True)
        self.ce.stage_model.set_selection(['/inst_source1'])
        self.win.show()
        make_active(self.win)
        # The dock layout comes back from the user's editor cache, which
        # every earlier run on this machine has written to, and it can
        # leave the code editor closed. Focus cannot go to a widget that
        # is not on screen.
        self.ce.show()
        self.ce.raise_()
        self.ce.code_frame.show()
        app.processEvents()
        arm(self.ce)
        give_focus(self.editor)

    def tearDown(self):
        # The popup is a window of its own. Left up, it outlives the one
        # it belongs to and is freed later, somewhere else.
        self.editor.hide_completions()
        self.ce.stage_model.effected_layers.clear()
        close_window(self.win)
        self.win = None
        restore_prefs(self.saved)

    def test_down_then_return_writes_what_was_highlighted(self):
        popup = self.editor.completer.popup()
        model = self.editor.completer.completionModel()
        self.assertTrue(self.editor.isVisible(), 'the editor is not on screen')
        if (QtWidgets.QApplication.focusWidget() is not self.editor
                and sys.platform == 'darwin'
                and QtWidgets.QApplication.platformName() == 'offscreen'):
            # Offscreen on macOS never makes a window active, so focus
            # stays wherever it first landed and no key can reach the
            # editor. Nothing here could pass or fail on its merits; with a
            # window server, or on any other platform, it runs.
            self.skipTest('offscreen on macOS cannot focus the editor')
        self.assertIs(QtWidgets.QApplication.focusWidget(), self.editor,
                      'the keys would go to something other than the editor')
        self.assertTrue(popup.isVisible(), 'nothing to drive')
        key_click(popup, QtCore.Qt.Key_Down)
        app.processEvents()
        chosen = model.data(popup.currentIndex())
        self.assertTrue(chosen, 'nothing was highlighted to take')
        key_click(popup, QtCore.Qt.Key_Return)
        app.processEvents()
        last_line = self.editor.toPlainText().split('\n')[-1]
        self.assertEqual(chosen, last_line,
                         'the word that was chosen was never written')
        self.assertFalse(popup.isVisible())


if __name__ == '__main__':
    unittest.main()
