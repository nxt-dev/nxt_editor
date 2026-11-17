"""Completion keeps up with typing.

The list opens once typing pauses, or at once after a dot. While it is
open, typing more of the same name only filters it. jedi is asked on a
worker thread, so a slow answer never holds up a key, and an answer about a
spot the cursor has left is not shown. What a compute's import lines ask
for is worked out once while they stay the same.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt import DATA_STATE
from nxt_editor import user_dir
from nxt_editor.dockwidgets import code_completion

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

PREFS = (
    user_dir.USER_PREF.CE_COMPLETE_PYTHON,
    user_dir.USER_PREF.CE_COMPLETE_MODULES,
    user_dir.USER_PREF.CE_COMPLETE_NODE,
    user_dir.USER_PREF.CE_COMPLETE_DOCUMENT,
    user_dir.USER_PREF.CE_COMPLETE_HOST,
    user_dir.USER_PREF.CE_COMPLETE_JEDI,
)


def wait_for(condition, seconds=5.0):
    """Let events run until condition() holds, or the time is up."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class SlowJedi(object):
    """Stands in for jedi: answers only once let go, like a slow question."""

    def __init__(self, names):
        self.names = names
        self.gate = threading.Event()
        self.asked = 0

    def Interpreter(self, source, namespaces):
        owner = self

        class Script(object):
            def complete(self, line, column):
                owner.asked += 1
                owner.gate.wait(5)
                return [types.SimpleNamespace(name=n) for n in owner.names]
        return Script()


class CompletionTyping(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='nxt_completion_typing_')
        cls.graph = os.path.join(cls.tmp, 'typing.nxt')
        with open(cls.graph, 'w') as fp:
            json.dump({'version': '1.17', 'alias': 'typing',
                       'nodes': {'/node': {'code': ['']}}}, fp)
        cls.win = MainWindow(filepath=cls.graph)
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.actions = cls.win.code_editor_actions
        cls.win.model.data_state = DATA_STATE.RAW
        cls.win.model.set_selection(['/node'])
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.saved = {key: user_dir.user_prefs.get(key) for key in PREFS}
        self.auto = self.actions.autocomplete_action.isChecked()
        self.actions.autocomplete_action.setChecked(True)
        for action, _pref, _default in self.actions.completion_source_actions:
            action.setChecked(True)
        focus = mock.patch.object(self.editor, 'hasFocus', return_value=True)
        focus.start()
        self.addCleanup(focus.stop)
        code_completion.JEDI._cache = (None, [])
        self.load('')

    def tearDown(self):
        self.editor.hide_completions()
        wait_for(lambda: not self.editor.jedi_busy, 2)
        code_completion.JEDI._cache = (None, [])
        self.actions.autocomplete_action.setChecked(self.auto)
        for key, value in self.saved.items():
            if value is None:
                try:
                    user_dir.user_prefs.pop(key)
                except KeyError:
                    pass
            else:
                user_dir.user_prefs[key] = value

    def load(self, text):
        self.editor.setReadOnly(False)
        self.ce.editing_active = True
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(cursor)
        self.editor.invalidate_completion_words()

    def type(self, text):
        for char in text:
            event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, 0,
                                    QtCore.Qt.NoModifier, char)
            self.editor.keyPressEvent(event)

    def shown(self):
        return self.editor.completer.popup().isVisible()

    # -- opening -----------------------------------------------------------

    def test_the_list_waits_for_typing_to_pause(self):
        self.type('pri')
        self.assertFalse(self.shown(), 'opened while still typing')
        self.assertTrue(self.editor.completion_timer.isActive())
        self.assertTrue(wait_for(self.shown), 'never opened')
        self.assertIn('print', self.editor.completer.model().stringList())

    def test_a_dot_opens_it_at_once(self):
        self.load('import os\n')
        self.type('os.')
        self.assertTrue(self.shown())
        self.assertIn('os.path', self.editor.completer.model().stringList())

    def test_it_does_not_open_where_the_cursor_has_left(self):
        self.load('pri\n\nzzz')
        cursor = self.editor.textCursor()
        cursor.setPosition(3)
        self.editor.setTextCursor(cursor)
        self.type('n')
        cursor.setPosition(len(self.editor.toPlainText()))
        self.editor.setTextCursor(cursor)
        wait_for(lambda: False, 0.4)
        self.assertFalse(self.shown())

    def test_at_most_twelve_rows_show(self):
        self.assertEqual(12, self.editor.completer.maxVisibleItems())

    # -- filtering ---------------------------------------------------------

    def test_typing_more_of_a_name_only_filters(self):
        self.type('pr')
        self.assertTrue(wait_for(self.shown))
        model = self.editor.completer.model()
        with mock.patch.object(self.editor, 'build_completion_words',
                               side_effect=AssertionError('rebuilt')):
            self.type('in')
        self.assertTrue(self.shown())
        self.assertIs(model, self.editor.completer.model())
        self.assertEqual('print', self.editor.completer.currentCompletion())

    def test_a_new_dot_builds_it_again(self):
        self.load('import os\n')
        self.type('os.')
        first = self.editor.completer.model()
        self.type('path.')
        self.assertIsNot(first, self.editor.completer.model())
        self.assertIn('os.path.join',
                      self.editor.completer.model().stringList())

    # -- imports -------------------------------------------------------------

    def test_an_import_that_fails_is_tried_once_while_typing(self):
        self.load('import nxt_no_such_module_here\nx = ')
        real = __import__('importlib').import_module
        with mock.patch('importlib.import_module',
                        side_effect=real) as imported:
            for _ in range(5):
                self.type('a')
                self.editor.imported_modules()
        tried = [c for c in imported.call_args_list
                 if c.args and c.args[0] == 'nxt_no_such_module_here']
        self.assertEqual(1, len(tried))

    def test_a_reloaded_module_is_the_one_offered(self):
        first = types.ModuleType('nxt_typing_probe')
        sys.modules['nxt_typing_probe'] = first
        try:
            self.load('import nxt_typing_probe\n')
            self.assertIs(first,
                          self.editor.imported_modules()['nxt_typing_probe'])
            second = types.ModuleType('nxt_typing_probe')
            sys.modules['nxt_typing_probe'] = second
            self.type('x')
            self.assertIs(second,
                          self.editor.imported_modules()['nxt_typing_probe'])
        finally:
            sys.modules.pop('nxt_typing_probe', None)

    # -- jedi ----------------------------------------------------------------

    def slow_jedi(self, names):
        jedi = SlowJedi(names)
        for patch in (mock.patch.object(code_completion.Jedi, 'installed',
                                        staticmethod(lambda: True)),
                      mock.patch.object(code_completion.JEDI, '_load',
                                        return_value=jedi)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(jedi.gate.set)
        return jedi

    def test_a_slow_jedi_does_not_hold_up_typing(self):
        jedi = self.slow_jedi(['upper', 'lower'])
        self.load("label = 'x'\nlabel.")
        started = time.time()
        self.editor.ask_jedi()
        self.type('u')
        self.assertLess(time.time() - started, 0.5)
        self.assertTrue(self.editor.jedi_busy)
        jedi.gate.set()
        self.assertTrue(wait_for(lambda: 'label.upper' in
                                 self.editor.completer.model().stringList()))
        self.assertTrue(self.shown())
        self.assertEqual(1, jedi.asked)

    def test_an_answer_about_a_spot_left_behind_is_not_shown(self):
        jedi = self.slow_jedi(['upper'])
        self.load("label = 'x'\nlabel.")
        self.editor.ask_jedi()
        self.assertTrue(self.editor.jedi_busy)
        self.load("label = 'x'\nother = 1\n")
        jedi.gate.set()
        self.assertTrue(wait_for(lambda: not self.editor.jedi_busy))
        app.processEvents()
        self.assertFalse(self.shown())

    def test_ctrl_space_shows_jedis_answer_when_it_comes(self):
        jedi = self.slow_jedi(['upper'])
        self.actions.autocomplete_action.setChecked(False)
        self.load("label = 'x'\nlabel.")
        self.editor.update_completions(force=True)
        self.assertTrue(self.editor.jedi_busy)
        jedi.gate.set()
        self.assertTrue(wait_for(lambda: 'label.upper' in
                                 self.editor.completer.model().stringList()))
        self.assertTrue(self.shown())


if __name__ == '__main__':
    unittest.main()
