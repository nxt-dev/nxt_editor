# Builtin
import logging
import os
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt import nxt_path

path_logger = logging.getLogger(nxt_path.__name__)
path_logger.propagate = False

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# Imported after the application exists, because building the main window
# touches widgets.
from nxt_editor.main_window import MainWindow  # noqa: E402

SAMPLE = "\n".join([
    "import os",
    "value = os.path.join('a', 'b')",
    "other = value + value",
    "def run(value):",
    "    return (value, [1, 2], {'k': value})",
])


class CodeEditorTestCase(unittest.TestCase):
    """Shared window for the code editor tests.

    Building a main window is the only way to get a code editor with its
    actions wired up, so it is built once and each test resets the text.
    """

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.win = MainWindow(filepath="StageInstanceTest.nxt")
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.bar = cls.ce.find_bar

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def load(self, text):
        """Put known text into an editable editor."""
        self.editor.setReadOnly(False)
        self.ce.editing_active = True
        self.editor.setPlainText(text)
        app.processEvents()

    def put_cursor(self, position):
        cursor = self.editor.textCursor()
        cursor.setPosition(position)
        self.editor.setTextCursor(cursor)
        app.processEvents()
        return cursor

    def layer(self, name):
        return self.editor.extra_selection_layers.get(name, [])


class TestFind(CodeEditorTestCase):

    def setUp(self):
        self.load(SAMPLE)
        self.bar.open_find()
        self.bar.case_button.setChecked(False)
        self.bar.word_button.setChecked(False)
        self.bar.regex_button.setChecked(False)
        self.bar.find_field.setText("value")
        app.processEvents()

    def tearDown(self):
        self.bar.close_bar()

    def test_finds_every_occurrence(self):
        self.assertEqual(6, len(self.bar.matches))
        self.assertIn("of 6", self.bar.count_label.text())

    def test_next_and_previous_wrap(self):
        self.bar.current = len(self.bar.matches) - 1
        self.bar.find_next()
        self.assertEqual(0, self.bar.current)
        self.bar.find_previous()
        self.assertEqual(len(self.bar.matches) - 1, self.bar.current)

    def test_stepping_selects_the_match(self):
        self.bar.find_next()
        self.assertEqual("value",
                         self.editor.textCursor().selectedText())

    def test_whole_word(self):
        self.bar.word_button.setChecked(True)
        app.processEvents()
        self.assertEqual(6, len(self.bar.matches))
        self.bar.find_field.setText("val")
        app.processEvents()
        self.assertEqual(0, len(self.bar.matches))

    def test_match_case(self):
        self.bar.find_field.setText("VALUE")
        app.processEvents()
        self.assertEqual(6, len(self.bar.matches))
        self.bar.case_button.setChecked(True)
        app.processEvents()
        self.assertEqual(0, len(self.bar.matches))

    def test_regex(self):
        self.bar.regex_button.setChecked(True)
        self.bar.find_field.setText("o[a-z]+")
        app.processEvents()
        self.assertTrue(self.bar.matches)

    def test_invalid_regex_is_reported_not_raised(self):
        self.bar.regex_button.setChecked(True)
        self.bar.find_field.setText("(unclosed")
        app.processEvents()
        self.assertEqual("bad pattern", self.bar.count_label.text())
        self.assertEqual([], self.bar.matches)

    def test_empty_pattern_matches_nothing(self):
        self.bar.find_field.setText("")
        app.processEvents()
        self.assertEqual([], self.bar.matches)

    def test_pattern_that_can_match_nothing(self):
        # "a*" matches the empty string at every position, which would
        # otherwise report a hit per character.
        self.bar.regex_button.setChecked(True)
        self.bar.find_field.setText("z*")
        app.processEvents()
        self.assertEqual([], self.bar.matches)

    def test_highlights_compose_with_the_current_line(self):
        self.assertEqual(5, len(self.layer("find_matches")))
        self.assertEqual(1, len(self.layer("find_current")))
        self.assertEqual(1, len(self.layer("current_line")))

    def test_closing_clears_the_highlights(self):
        self.bar.close_bar()
        self.assertEqual([], self.layer("find_matches"))
        self.assertEqual([], self.layer("find_current"))

    def test_search_works_while_the_dock_is_not_visible(self):
        # A dock tabbed behind another is not visible, and find still has
        # to work in it.
        self.bar.setVisible(False)
        self.bar.find_field.setText("other")
        app.processEvents()
        self.assertEqual(1, len(self.bar.matches))


class TestReplace(CodeEditorTestCase):

    def setUp(self):
        self.load(SAMPLE)
        self.bar.open_find(replace=True)
        self.bar.case_button.setChecked(False)
        self.bar.word_button.setChecked(False)
        self.bar.regex_button.setChecked(False)
        self.bar.find_field.setText("value")
        self.bar.replace_field.setText("thing")
        app.processEvents()

    def tearDown(self):
        self.bar.close_bar()

    def test_replace_one(self):
        self.bar.current = 0
        self.bar.replace_current()
        app.processEvents()
        self.assertEqual(1, self.editor.toPlainText().count("thing"))
        self.assertEqual(5, self.editor.toPlainText().count("value"))

    def test_replace_all(self):
        self.bar.replace_all()
        app.processEvents()
        text = self.editor.toPlainText()
        self.assertEqual(6, text.count("thing"))
        self.assertNotIn("value", text)

    def test_replace_all_is_one_undo_step(self):
        self.bar.replace_all()
        app.processEvents()
        self.editor.undo()
        app.processEvents()
        self.assertEqual(SAMPLE, self.editor.toPlainText())

    def test_read_only_blocks_replacing(self):
        self.editor.setReadOnly(True)
        self.bar.update_replace_enabled()
        self.assertFalse(self.bar.replace_button.isEnabled())
        self.bar.replace_all()
        self.assertEqual(SAMPLE, self.editor.toPlainText())
        self.editor.setReadOnly(False)


class TestHighlighting(CodeEditorTestCase):

    def test_word_under_cursor(self):
        self.load(SAMPLE)
        self.put_cursor(SAMPLE.index("value"))
        self.assertEqual("value", self.editor.word_under_cursor()[0])

    def test_occurrences_highlighted(self):
        self.load(SAMPLE)
        self.put_cursor(SAMPLE.index("value"))
        self.assertEqual(6, len(self.layer("occurrences")))

    def test_a_lone_word_is_not_highlighted(self):
        self.load("solo = 1\nother = 2")
        self.put_cursor(1)
        self.assertEqual([], self.layer("occurrences"))

    def test_matched_brackets(self):
        text = "x = foo(a, [b, c], {'d': e})"
        self.load(text)
        self.put_cursor(text.index("(") + 1)
        self.assertEqual(2, len(self.layer("brackets")))

    def test_bracket_partners(self):
        text = "x = foo(a, [b, c], {'d': e})"
        editor = self.editor
        self.assertEqual(len(text) - 1,
                         editor.match_bracket(text, text.index("(")))
        self.assertEqual(text.index("("),
                         editor.match_bracket(text, len(text) - 1))
        self.assertEqual(text.index("]"),
                         editor.match_bracket(text, text.index("[")))
        self.assertEqual(text.index("}"),
                         editor.match_bracket(text, text.index("{")))

    def test_unbalanced_bracket(self):
        self.assertIsNone(self.editor.match_bracket("foo(a", 3))
        self.load("foo(a")
        self.put_cursor(4)
        self.assertEqual(1, len(self.layer("brackets")))


class TestLineEditing(CodeEditorTestCase):

    def test_duplicate_line(self):
        self.load("one\ntwo\nthree")
        self.put_cursor(0)
        self.editor.duplicate_lines()
        self.assertEqual("one\none\ntwo\nthree", self.editor.toPlainText())

    def test_move_line_up(self):
        self.load("one\ntwo\nthree")
        self.put_cursor(self.editor.toPlainText().index("two"))
        self.editor.move_lines(-1)
        self.assertEqual("two\none\nthree", self.editor.toPlainText())
        self.assertEqual(0, self.editor.textCursor().blockNumber())

    def test_move_line_down(self):
        self.load("one\ntwo\nthree")
        self.put_cursor(0)
        self.editor.move_lines(1)
        self.assertEqual("two\none\nthree", self.editor.toPlainText())

    def test_move_stops_at_the_edges(self):
        self.load("one\ntwo\nthree")
        self.put_cursor(0)
        self.editor.move_lines(-1)
        self.assertEqual("one\ntwo\nthree", self.editor.toPlainText())
        self.put_cursor(self.editor.toPlainText().index("three"))
        self.editor.move_lines(1)
        self.assertEqual("one\ntwo\nthree", self.editor.toPlainText())

    def test_delete_middle_line(self):
        self.load("one\ntwo\nthree")
        self.put_cursor(self.editor.toPlainText().index("two"))
        self.editor.delete_lines()
        self.assertEqual("one\nthree", self.editor.toPlainText())

    def test_delete_last_line(self):
        self.load("one\ntwo\nthree")
        self.put_cursor(self.editor.toPlainText().index("three"))
        self.editor.delete_lines()
        self.assertEqual("one\ntwo", self.editor.toPlainText())

    def test_delete_the_only_line(self):
        self.load("only")
        self.put_cursor(0)
        self.editor.delete_lines()
        self.assertEqual("", self.editor.toPlainText())

    def test_delete_a_multi_line_selection(self):
        self.load("a\nb\nc\nd")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(3, QtGui.QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.delete_lines()
        self.assertEqual("c\nd", self.editor.toPlainText())

    def test_read_only_blocks_line_edits(self):
        self.load("one\ntwo")
        self.editor.setReadOnly(True)
        self.put_cursor(0)
        self.editor.duplicate_lines()
        self.editor.delete_lines()
        self.editor.move_lines(1)
        self.assertEqual("one\ntwo", self.editor.toPlainText())
        self.editor.setReadOnly(False)

    def test_expand_selection_grows(self):
        self.load(SAMPLE)
        self.put_cursor(SAMPLE.index("value") + 2)
        self.editor.expand_selection()
        self.assertEqual("value", self.editor.textCursor().selectedText())
        self.editor.expand_selection()
        self.assertEqual("value = os.path.join('a', 'b')",
                         self.editor.textCursor().selectedText())
        self.editor.expand_selection()
        self.assertEqual(len(SAMPLE),
                         len(self.editor.textCursor().selectedText()))


class TestCompletion(CodeEditorTestCase):

    def setUp(self):
        self.load(SAMPLE)
        self.editor.ce_actions.autocomplete_action.setChecked(True)

    def tearDown(self):
        self.editor.hide_completions()

    def type_at_end(self, text):
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        return cursor

    def test_word_sources(self):
        words = self.editor.build_completion_words()
        self.assertIn("return", words)
        self.assertIn("enumerate", words)
        self.assertIn("value", words)
        self.assertTrue(any(w.startswith("${file::") for w in words),
                        "nxt token prefixes should be offered")

    def test_prefix_reading(self):
        self.type_at_end("\nretu")
        self.assertEqual("retu", self.editor.completion_prefix())

    def test_dotted_prefix_is_kept_whole(self):
        self.type_at_end("\nself.va")
        self.assertEqual("self.va", self.editor.completion_prefix())

    def test_popup_and_insert(self):
        self.type_at_end("\nretu")
        self.editor.update_completions(force=True)
        self.assertTrue(self.editor.completer.popup().isVisible())
        self.editor.insert_completion("return")
        self.assertTrue(self.editor.toPlainText().endswith("return"))

    def test_shortcuts_stand_down_while_the_popup_is_up(self):
        actions = self.editor.ce_actions
        self.type_at_end("\nretu")
        self.editor.update_completions(force=True)
        self.assertFalse(actions.new_line.isEnabled())
        self.assertFalse(actions.cancel_edit_action.isEnabled())
        self.editor.hide_completions()
        self.assertTrue(actions.new_line.isEnabled())
        self.assertTrue(actions.cancel_edit_action.isEnabled())

    def test_dismissing_the_popup_any_way_restores_shortcuts(self):
        # Escape and clicking away are handled inside QCompleter, so the
        # editor only learns about them from the popup being hidden.
        actions = self.editor.ce_actions
        self.type_at_end("\nretu")
        self.editor.update_completions(force=True)
        self.assertFalse(actions.new_line.isEnabled())
        self.editor.completer.popup().hide()
        app.processEvents()
        self.assertTrue(actions.new_line.isEnabled())

    def test_a_fully_typed_word_offers_nothing(self):
        self.type_at_end("\nreturn")
        self.editor.update_completions(force=True)
        self.assertFalse(self.editor.completer.popup().isVisible())

    def test_preference_off_means_no_popup_unless_forced(self):
        self.editor.ce_actions.autocomplete_action.setChecked(False)
        self.type_at_end("\nretu")
        self.editor.update_completions()
        self.assertFalse(self.editor.completer.popup().isVisible())
        self.editor.update_completions(force=True)
        self.assertTrue(self.editor.completer.popup().isVisible())

    def test_read_only_offers_nothing(self):
        self.editor.setReadOnly(True)
        self.editor.update_completions(force=True)
        self.assertFalse(self.editor.completer.popup().isVisible())
        self.editor.setReadOnly(False)


class TestShortcuts(CodeEditorTestCase):

    EXPECTED = {
        'Find In Code': 'Ctrl+F',
        'Replace In Code': 'Ctrl+H',
        'Find Next': 'F3',
        'Go To Line': 'Ctrl+G',
        'Duplicate Line': 'Ctrl+Shift+D',
        'Move Line Up': 'Alt+Up',
        'Move Line Down': 'Alt+Down',
        'Delete Line': 'Ctrl+Shift+K',
        'Expand Selection': 'Ctrl+D',
        'Complete Word': 'Ctrl+Space',
    }

    def test_shortcuts_are_bound(self):
        bound = {a.text(): a.shortcut().toString()
                 for a in self.editor.ce_actions.actions()}
        for name, expected in self.EXPECTED.items():
            self.assertEqual(expected, bound.get(name),
                             '%s should be %s' % (name, expected))

    def test_shortcuts_are_widget_scoped(self):
        # Ctrl+F, Ctrl+G and Ctrl+D are also bound on the main window. These
        # may only win while the code editor has focus.
        widget_scopes = (QtCore.Qt.WidgetShortcut,
                         QtCore.Qt.WidgetWithChildrenShortcut)
        for action in self.editor.ce_actions.actions():
            self.assertIn(action.shortcutContext(), widget_scopes,
                          '%s escapes the code editor' % action.text())


if __name__ == '__main__':
    unittest.main()
