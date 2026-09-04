"""Find and replace inside the code editor.

This is not the graph wide find and replace in find_rep.py. That one searches
node attributes across the whole stage; this one searches the compute you are
looking at, the way a text editor's find bar does.

The bar lives at the bottom of the code editor dock and is hidden until asked
for. It owns two of the editor's extra selection layers, one for every match
and one for the match the cursor is sitting on, so it composes with the
current line highlight rather than fighting it.
"""
# Builtin
import logging
import re

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
import nxt_editor
from nxt_editor.constants import FONTS

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

MATCH_COLOR = QtGui.QColor('#4A5A38')
CURRENT_MATCH_COLOR = QtGui.QColor('#8A6D24')
BAD_PATTERN_COLOR = QtGui.QColor('#5C2B2B')
# QTextCursor reports line breaks in a selection as U+2029, so this is how
# a multi line selection is recognised.
PARAGRAPH_SEP = u'\u2029'
# Kept as a name because the escape is easy to mangle when this
# file is edited by anything other than a person.
WORD_BOUNDARY = '\\b'


class FindLineEdit(QtWidgets.QLineEdit):
    """A line edit that reports the keys the find bar cares about.

    Return steps to the next match and Shift+Return to the previous one,
    which means neither can reach the editor's own Return binding while the
    bar has focus. Escape closes the bar.
    """
    find_next = QtCore.Signal()
    find_prev = QtCore.Signal()
    dismissed = QtCore.Signal()

    def __init__(self, editor, parent=None):
        super(FindLineEdit, self).__init__(parent=parent)
        self.editor = editor

    def focusInEvent(self, event):
        # The editor stands the main window's shortcuts down while it has
        # focus so typing cannot fire them. Typing happens in here too, so
        # keep them down rather than handing Ctrl+N back mid-search.
        self.editor.suspend_global_actions()
        super(FindLineEdit, self).focusInEvent(event)

    def focusOutEvent(self, event):
        self.editor.restore_global_actions()
        super(FindLineEdit, self).focusOutEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                self.find_prev.emit()
            else:
                self.find_next.emit()
            return
        if key == QtCore.Qt.Key_Escape:
            self.dismissed.emit()
            return
        super(FindLineEdit, self).keyPressEvent(event)


class CodeFindBar(QtWidgets.QWidget):
    """Find and replace for one code editor.

    :param editor: the NxtCodeEditor being searched
    :param parent: the CodeEditor dock widget
    """

    def __init__(self, editor, parent=None):
        super(CodeFindBar, self).__init__(parent=parent)
        self.editor = editor
        self.ce_widget = parent
        # (start, end) document positions of every match, in document order
        self.matches = []
        self.current = -1
        self._searching = False
        # Whether the bar is open, as opposed to whether Qt considers it
        # visible. A dock tabbed behind another is not visible, and the
        # search still has to work in it.
        self.active = False

        self.setVisible(False)
        self.setStyleSheet('background-color: #3E3E3E;')

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(4, 3, 4, 4)
        layout.setSpacing(3)
        self.setLayout(layout)

        # --- find row -------------------------------------------------
        find_row = QtWidgets.QHBoxLayout()
        find_row.setSpacing(3)
        layout.addLayout(find_row)

        self.find_field = FindLineEdit(editor, parent=self)
        self.find_field.setPlaceholderText('Find')
        self.find_field.setFont(FONTS.monospace_font(9))
        self.find_field.textChanged.connect(self.update_matches)
        self.find_field.find_next.connect(self.find_next)
        self.find_field.find_prev.connect(self.find_previous)
        self.find_field.dismissed.connect(self.close_bar)
        find_row.addWidget(self.find_field)

        self.count_label = QtWidgets.QLabel('', parent=self)
        self.count_label.setFont(FONTS.monospace_font(8))
        self.count_label.setStyleSheet('color: grey;')
        self.count_label.setMinimumWidth(78)
        self.count_label.setAlignment(QtCore.Qt.AlignRight |
                                      QtCore.Qt.AlignVCenter)
        find_row.addWidget(self.count_label)

        self.case_button = self._toggle('Aa', 'Match case')
        self.word_button = self._toggle('W', 'Whole word only')
        self.regex_button = self._toggle('.*', 'Regular expression')
        for button in (self.case_button, self.word_button, self.regex_button):
            button.toggled.connect(self.update_matches)
            find_row.addWidget(button)

        self.prev_button = self._button('<', 'Previous match (Shift+F3)')
        self.prev_button.clicked.connect(self.find_previous)
        find_row.addWidget(self.prev_button)
        self.next_button = self._button('>', 'Next match (F3)')
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)

        self.replace_toggle = self._toggle('Replace', 'Show replace')
        self.replace_toggle.toggled.connect(self.set_replace_visible)
        find_row.addWidget(self.replace_toggle)

        self.close_button = self._button('x', 'Close (Esc)')
        self.close_button.clicked.connect(self.close_bar)
        find_row.addWidget(self.close_button)

        # --- replace row ----------------------------------------------
        self.replace_widget = QtWidgets.QWidget(parent=self)
        self.replace_widget.setVisible(False)
        layout.addWidget(self.replace_widget)

        replace_row = QtWidgets.QHBoxLayout()
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.setSpacing(3)
        self.replace_widget.setLayout(replace_row)

        self.replace_field = FindLineEdit(editor, parent=self.replace_widget)
        self.replace_field.setPlaceholderText('Replace with')
        self.replace_field.setFont(FONTS.monospace_font(9))
        self.replace_field.find_next.connect(self.replace_current)
        self.replace_field.dismissed.connect(self.close_bar)
        replace_row.addWidget(self.replace_field)

        self.replace_button = self._button('Replace', 'Replace this match')
        self.replace_button.clicked.connect(self.replace_current)
        replace_row.addWidget(self.replace_button)
        self.replace_all_button = self._button('Replace All',
                                               'Replace every match')
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_row.addWidget(self.replace_all_button)

        self.locked_label = QtWidgets.QLabel('', parent=self.replace_widget)
        self.locked_label.setFont(FONTS.monospace_font(8))
        self.locked_label.setStyleSheet('color: #B58900;')
        replace_row.addWidget(self.locked_label)

    # -- construction helpers -----------------------------------------

    def _toggle(self, text, tip):
        button = QtWidgets.QToolButton(parent=self)
        button.setText(text)
        button.setToolTip(tip)
        button.setCheckable(True)
        button.setFont(FONTS.monospace_font(8))
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        return button

    def _button(self, text, tip):
        button = QtWidgets.QToolButton(parent=self)
        button.setText(text)
        button.setToolTip(tip)
        button.setFont(FONTS.monospace_font(8))
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        return button

    # -- opening and closing ------------------------------------------

    def open_find(self, replace=False):
        """Show the bar, seeded with the editor's selection if there is one.

        :param replace: also show the replace row
        :type replace: bool
        """
        selected = self.editor.textCursor().selectedText()
        # QTextCursor uses U+2029 for line breaks, so a multi line selection
        # is not a sensible seed for a find field.
        if selected and PARAGRAPH_SEP not in selected:
            self.find_field.setText(selected)
        self.setVisible(True)
        self.active = True
        if replace:
            self.replace_toggle.setChecked(True)
        self.update_replace_enabled()
        self.update_matches()
        self.find_field.setFocus()
        self.find_field.selectAll()

    def close_bar(self):
        self.setVisible(False)
        self.active = False
        self.clear_highlights()
        self.matches = []
        self.current = -1
        self.editor.setFocus()

    def set_replace_visible(self, visible):
        self.replace_widget.setVisible(visible)
        if visible:
            self.update_replace_enabled()
            self.replace_field.setFocus()

    def update_replace_enabled(self):
        """Replacing needs the editor to be in editing mode.

        The code editor is read only until it is double clicked into, so
        say why the buttons are dead rather than letting them look broken.
        """
        editable = not self.editor.isReadOnly()
        self.replace_button.setEnabled(editable)
        self.replace_all_button.setEnabled(editable)
        if editable:
            self.locked_label.setText('')
        else:
            self.locked_label.setText('double click the code to edit')

    # -- searching -----------------------------------------------------

    def build_regex(self):
        """Turn the find field and the toggles into one compiled pattern.

        :return: compiled re pattern, or None when the field is empty or
            the pattern will not compile
        """
        text = self.find_field.text()
        if not text:
            return None
        pattern = text if self.regex_button.isChecked() else re.escape(text)
        if self.word_button.isChecked():
            pattern = WORD_BOUNDARY + '(?:' + pattern + ')' + WORD_BOUNDARY
        flags = 0 if self.case_button.isChecked() else re.IGNORECASE
        try:
            return re.compile(pattern, flags)
        except re.error:
            return None

    def update_matches(self):
        """Re-run the search and repaint the highlights.

        Keeps the cursor where it is. Stepping to a match is find_next's job.
        """
        if not self.active:
            return
        self.matches = []
        text = self.find_field.text()
        expression = self.build_regex()
        if expression is None:
            self.clear_highlights()
            if not text:
                self.count_label.setText('')
                self._set_field_error(False)
            else:
                self.count_label.setText('bad pattern')
                self._set_field_error(True)
            self.current = -1
            return
        self._set_field_error(False)
        document = self.editor.toPlainText()
        for match in expression.finditer(document):
            start, end = match.start(), match.end()
            if end == start:
                # A pattern that can match nothing, like "a*", would
                # otherwise report a hit at every position in the document.
                continue
            self.matches.append((start, end))
        if not self.matches:
            self.count_label.setText('no results')
            self.current = -1
            self.clear_highlights()
            return
        self.current = self._match_at_or_after(self.editor.textCursor().
                                               selectionStart())
        self._paint()

    def _match_at_or_after(self, position):
        for idx, (start, _) in enumerate(self.matches):
            if start >= position:
                return idx
        return 0

    def _set_field_error(self, bad):
        if bad:
            self.find_field.setStyleSheet('background-color: %s;'
                                          % BAD_PATTERN_COLOR.name())
        else:
            self.find_field.setStyleSheet('')

    def find_next(self):
        self._step(1)

    def find_previous(self):
        self._step(-1)

    def _step(self, direction):
        if not self.active:
            self.open_find()
            return
        if not self.matches:
            self.update_matches()
            if not self.matches:
                return
        else:
            self.current = (self.current + direction) % len(self.matches)
        self._go_to_current()

    def _go_to_current(self):
        if not self.matches:
            return
        start, end = self.matches[self.current]
        cursor = self.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
        # Moving the cursor re-runs the editor's own highlighting, so paint
        # after, not before.
        self._searching = True
        try:
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()
        finally:
            self._searching = False
        self._paint()

    # -- replacing -----------------------------------------------------

    def replace_current(self):
        if self.editor.isReadOnly() or not self.matches:
            return
        if self.current < 0:
            self.current = 0
        start, end = self.matches[self.current]
        cursor = self.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
        cursor.insertText(self.replace_field.text())
        self.update_matches()
        if self.matches:
            self.current = self._match_at_or_after(cursor.position())
            self._go_to_current()

    def replace_all(self):
        if self.editor.isReadOnly():
            return
        self.update_matches()
        if not self.matches:
            return
        replacement = self.replace_field.text()
        count = len(self.matches)
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        try:
            # Back to front, so replacing does not move the matches that
            # have not been handled yet.
            for start, end in reversed(self.matches):
                cursor.setPosition(start)
                cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
                cursor.insertText(replacement)
        finally:
            cursor.endEditBlock()
        self.update_matches()
        self.count_label.setText('%d replaced' % count)

    # -- highlighting ---------------------------------------------------

    def clear_highlights(self):
        self.editor.set_extra_selection_layer('find_matches', [])
        self.editor.set_extra_selection_layer('find_current', [])

    def _paint(self):
        every = []
        current = []
        document = self.editor.document()
        for idx, (start, end) in enumerate(self.matches):
            selection = QtWidgets.QTextEdit.ExtraSelection()
            cursor = QtGui.QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(end, QtGui.QTextCursor.KeepAnchor)
            selection.cursor = cursor
            if idx == self.current:
                selection.format.setBackground(CURRENT_MATCH_COLOR)
                current.append(selection)
            else:
                selection.format.setBackground(MATCH_COLOR)
                every.append(selection)
        self.editor.set_extra_selection_layer('find_matches', every)
        self.editor.set_extra_selection_layer('find_current', current)
        if self.matches:
            self.count_label.setText('%d of %d' % (self.current + 1,
                                                   len(self.matches)))

    def on_editor_text_changed(self):
        """The document moved under us, so the recorded offsets are stale."""
        if self.active and not self._searching:
            self.update_matches()
