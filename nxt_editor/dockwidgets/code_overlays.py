"""Panels that float over the code editor.

Two of them, both modelled on the equivalents in VS Code:

    FindOverlay      top right corner, find and replace in this compute
    GotoLineOverlay  dropped from the top centre, jump to a line number

They float above the text rather than taking a strip of the dock, so the
code never reflows when one opens, and they position themselves against the
editor so they follow it wherever the dock ends up.

This is not the graph wide find and replace in find_rep.py. That one
searches node attributes across the whole stage; this one searches the
compute in front of you.
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
# QTextCursor reports line breaks in a selection as U+2029, so this is how a
# multi line selection is recognised.
PARAGRAPH_SEP = u'\u2029'
# Kept as a name because the escape is easy to mangle when this file is
# edited by anything other than a person.
WORD_BOUNDARY = '\\b'

MARGIN = 10
PANEL_QSS = '''
QFrame#editorOverlay {
    background-color: #313131;
    border: 1px solid #4C4C4C;
    border-radius: 4px;
}
QFrame#editorOverlay QLineEdit {
    background-color: #232323;
    border: 1px solid #4C4C4C;
    border-radius: 2px;
    color: #DCDCDC;
    selection-background-color: #2A5A8A;
    padding: 1px 3px;
}
QFrame#editorOverlay QLineEdit:focus {
    border: 1px solid #6E9ED6;
}
QFrame#editorOverlay QLineEdit[invalid="true"] {
    border: 1px solid #B14A4A;
}
QFrame#editorOverlay QLabel {
    color: #9A9A9A;
    background: transparent;
}
QFrame#editorOverlay QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    color: #C8C8C8;
    padding: 0px 2px;
}
QFrame#editorOverlay QToolButton:hover {
    background-color: #454545;
}
QFrame#editorOverlay QToolButton:checked {
    background-color: #48684A;
    border: 1px solid #6D946F;
}
QFrame#editorOverlay QToolButton#overlayChevron:checked {
    background: transparent;
    border: 1px solid transparent;
}
QFrame#editorOverlay QToolButton:disabled {
    color: #6A6A6A;
}
'''


class OverlayLineEdit(QtWidgets.QLineEdit):
    """A line edit that reports the keys an overlay cares about.

    Return and Escape are bound to editor actions, and a QAction shortcut is
    consumed before a focused widget ever sees the key. These overlays are
    children of the editor, so the keys are claimed here instead.
    """
    accepted = QtCore.Signal()
    accepted_back = QtCore.Signal()
    dismissed = QtCore.Signal()

    def __init__(self, editor, parent=None):
        super(OverlayLineEdit, self).__init__(parent=parent)
        self.editor = editor

    def focusInEvent(self, event):
        # The editor stands the main window's shortcuts down while it has
        # focus so typing cannot fire them. Typing happens in here too, so
        # keep them down rather than handing Ctrl+N back mid search.
        self.editor.suspend_global_actions()
        super(OverlayLineEdit, self).focusInEvent(event)

    def focusOutEvent(self, event):
        self.editor.restore_global_actions()
        super(OverlayLineEdit, self).focusOutEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                self.accepted_back.emit()
            else:
                self.accepted.emit()
            return
        if key == QtCore.Qt.Key_Escape:
            self.dismissed.emit()
            return
        super(OverlayLineEdit, self).keyPressEvent(event)


class EditorOverlay(QtWidgets.QFrame):
    """Base for a panel that floats over the code editor.

    Subclasses lay out their own contents and say where they sit by
    implementing `overlay_position`.

    :param editor: the NxtCodeEditor being floated over
    """

    def __init__(self, editor):
        super(EditorOverlay, self).__init__(parent=editor)
        self.editor = editor
        self.setObjectName('editorOverlay')
        self.setStyleSheet(PANEL_QSS)
        self.setVisible(False)
        # Whether the panel is open, as opposed to whether Qt considers it
        # visible. A dock tabbed behind another is not visible, and a search
        # still has to work in it.
        self.active = False
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 3)
        shadow.setColor(QtGui.QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)

    def overlay_position(self):
        """Top left corner this panel wants, in editor coordinates.

        :rtype: QtCore.QPoint
        """
        raise NotImplementedError

    def scrollbar_allowance(self):
        """How much room the editor's vertical scrollbar is taking."""
        scrollbar = self.editor.verticalScrollBar()
        return scrollbar.width() if scrollbar.isVisible() else 0

    def available_width(self):
        """How much of the editor a panel may use."""
        return self.editor.width() - self.scrollbar_allowance()

    def reposition(self):
        if not self.active:
            return
        # A panel wider than the editor would hang off the edge, so cap it
        # and let the fields inside give up their width.
        self.setMaximumWidth(max(120, self.available_width() - 2 * MARGIN))
        self.adjustSize()
        self.move(self.overlay_position())
        self.raise_()

    def open_overlay(self):
        self.active = True
        self.setVisible(True)
        self.reposition()

    def close_overlay(self):
        self.active = False
        self.setVisible(False)
        self.editor.setFocus()


class FindOverlay(EditorOverlay):
    """Find and replace, floating in the editor's top right corner.

    It owns two of the editor's extra selection layers, one for every match
    and one for the match the cursor is on, so it composes with the current
    line highlight rather than fighting it.
    """

    def __init__(self, editor, ce_widget=None):
        super(FindOverlay, self).__init__(editor)
        self.ce_widget = ce_widget
        # (start, end) document positions of every match, in document order
        self.matches = []
        self.current = -1
        self._searching = False

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)
        self.setLayout(layout)

        # --- find row -------------------------------------------------
        find_row = QtWidgets.QHBoxLayout()
        find_row.setSpacing(2)
        layout.addLayout(find_row)

        # The chevron expands the replace row, the way the same control
        # does in VS Code.
        self.expand_button = self._button(u'▸', 'Toggle replace')
        self.expand_button.setObjectName('overlayChevron')
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(self.set_replace_visible)
        find_row.addWidget(self.expand_button)

        self.find_field = OverlayLineEdit(editor, parent=self)
        self.find_field.setPlaceholderText('Find')
        self.find_field.setFont(FONTS.monospace_font(9))
        self.find_field.setMinimumWidth(130)
        self.find_field.setMaximumWidth(190)
        self.find_field.textChanged.connect(self.update_matches)
        self.find_field.accepted.connect(self.find_next)
        self.find_field.accepted_back.connect(self.find_previous)
        self.find_field.dismissed.connect(self.close_bar)
        find_row.addWidget(self.find_field)

        # Inside the field rather than beside it, so the panel stays narrow
        # enough to leave the code readable underneath.
        self.regex_button = self._field_toggle('.*', 'Regular expression')
        self.word_button = self._field_toggle('ab', 'Whole word only')
        self.case_button = self._field_toggle('Aa', 'Match case')

        self.count_label = QtWidgets.QLabel('', parent=self)
        self.count_label.setFont(FONTS.monospace_font(8))
        self.count_label.setMinimumWidth(46)
        self.count_label.setAlignment(QtCore.Qt.AlignRight |
                                      QtCore.Qt.AlignVCenter)
        find_row.addWidget(self.count_label)

        self.prev_button = self._button(u'↑', 'Previous match (Shift+F3)')
        self.prev_button.clicked.connect(self.find_previous)
        find_row.addWidget(self.prev_button)
        self.next_button = self._button(u'↓', 'Next match (F3)')
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)

        self.close_button = self._button(u'✕', 'Close (Esc)')
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
        # Line the replace field up under the find field, past the chevron.
        replace_row.addSpacing(self.expand_button.sizeHint().width() + 3)

        self.replace_field = OverlayLineEdit(editor,
                                             parent=self.replace_widget)
        self.replace_field.setPlaceholderText('Replace')
        self.replace_field.setFont(FONTS.monospace_font(9))
        self.replace_field.setMinimumWidth(80)
        self.replace_field.setMaximumWidth(140)
        self.replace_field.accepted.connect(self.replace_current)
        self.replace_field.dismissed.connect(self.close_bar)
        replace_row.addWidget(self.replace_field)

        self.replace_button = self._button('Replace', 'Replace this match')
        self.replace_button.clicked.connect(self.replace_current)
        replace_row.addWidget(self.replace_button)
        self.replace_all_button = self._button('All',
                                               'Replace every match')
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_row.addWidget(self.replace_all_button)

        self.locked_label = QtWidgets.QLabel('', parent=self.replace_widget)
        self.locked_label.setFont(FONTS.monospace_font(8))
        self.locked_label.setStyleSheet('color: #C8A44A; background: none;')
        replace_row.addWidget(self.locked_label)
        replace_row.addStretch()

    def _text_icon(self, text, checked=False):
        """An icon that is just some text, for the in field toggles.

        A QAction inside a QLineEdit is drawn as an icon, and these toggles
        read better as their own shorthand than as any picture.

        :param text: the shorthand, such as "Aa"
        :type text: str
        :param checked: draw it as switched on
        :type checked: bool
        :rtype: QtGui.QIcon
        """
        font = FONTS.monospace_font(8)
        metrics = QtGui.QFontMetrics(font)
        try:
            text_width = metrics.horizontalAdvance(text)
        except AttributeError:
            text_width = metrics.boundingRect(text).width()
        width = max(16, text_width + 6)
        height = 15
        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if checked:
            painter.setBrush(QtGui.QColor('#48684A'))
            painter.setPen(QtGui.QColor('#6D946F'))
            painter.drawRoundedRect(0, 0, width - 1, height - 1, 3, 3)
        painter.setFont(font)
        painter.setPen(QtGui.QColor('#E0E0E0' if checked else '#9A9A9A'))
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, text)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _field_toggle(self, text, tip):
        """A checkable toggle living inside the find field.

        :rtype: QtWidgets.QAction
        """
        action = QtWidgets.QAction(self._text_icon(text), tip, self)
        action.setCheckable(True)
        action.setToolTip(tip)

        def redraw(checked):
            action.setIcon(self._text_icon(text, checked))

        action.toggled.connect(redraw)
        action.toggled.connect(self.update_matches)
        self.find_field.addAction(action,
                                  QtWidgets.QLineEdit.TrailingPosition)
        return action

    def _button(self, text, tip, checkable=False):
        button = QtWidgets.QToolButton(parent=self)
        button.setText(text)
        button.setToolTip(tip)
        button.setCheckable(checkable)
        button.setFont(FONTS.monospace_font(8))
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        return button

    # -- placement ------------------------------------------------------

    def overlay_position(self):
        x = self.available_width() - self.width() - MARGIN
        return QtCore.QPoint(max(MARGIN, x), MARGIN)

    def keep_cursor_clear(self):
        """Scroll a match down from behind the panel if it landed there.

        The panel sits over the first few lines on the right, so a match up
        there can be hidden by the thing that found it. At the very top of
        the document there is nothing left to scroll, and the panel stays
        where it is rather than jumping somewhere unexpected.
        """
        if not self.geometry().intersects(self.editor.cursorRect()):
            return
        scrollbar = self.editor.verticalScrollBar()
        line_height = self.editor.fontMetrics().lineSpacing()
        if line_height <= 0 or scrollbar.value() <= scrollbar.minimum():
            return
        overlap = ((self.geometry().bottom() + MARGIN)
                   - self.editor.cursorRect().top())
        lines = int(overlap / line_height) + 1
        scrollbar.setValue(max(scrollbar.minimum(),
                               scrollbar.value() - lines))

    # -- opening and closing --------------------------------------------

    def open_find(self, replace=False):
        """Show the panel, seeded with the editor's selection if there is one.

        :param replace: also show the replace row
        :type replace: bool
        """
        selected = self.editor.textCursor().selectedText()
        if selected and PARAGRAPH_SEP not in selected:
            self.find_field.setText(selected)
        self.open_overlay()
        if replace:
            self.expand_button.setChecked(True)
        self.update_replace_enabled()
        self.update_matches()
        self.find_field.setFocus()
        self.find_field.selectAll()

    def close_bar(self):
        self.close_overlay()
        self.clear_highlights()
        self.matches = []
        self.current = -1

    def set_replace_visible(self, visible):
        self.replace_widget.setVisible(visible)
        self.expand_button.setText(u'▾' if visible else u'▸')
        self.reposition()
        if visible:
            self.update_replace_enabled()
            self.replace_field.setFocus()

    def update_replace_enabled(self):
        """Replacing needs the editor to be in editing mode.

        The code editor is read only until it is double clicked into, so say
        why the buttons are dead rather than letting them look broken.
        """
        editable = not self.editor.isReadOnly()
        self.replace_button.setEnabled(editable)
        self.replace_all_button.setEnabled(editable)
        self.locked_label.setText('' if editable else 'double click to edit')

    # -- searching -------------------------------------------------------

    def build_regex(self):
        """Turn the find field and the toggles into one compiled pattern.

        :return: compiled re pattern, or None when the field is empty or the
            pattern will not compile
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

        Leaves the cursor where it is. Stepping to a match is find_next's job.
        """
        if not self.active:
            return
        self.matches = []
        text = self.find_field.text()
        expression = self.build_regex()
        if expression is None:
            self.clear_highlights()
            self.current = -1
            if not text:
                self.count_label.setText('')
                self._set_field_error(False)
            else:
                self.count_label.setText('bad pattern')
                self._set_field_error(True)
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
        start = self.editor.textCursor().selectionStart()
        self.current = self._match_at_or_after(start)
        self._paint()

    def _match_at_or_after(self, position):
        for idx, (start, _) in enumerate(self.matches):
            if start >= position:
                return idx
        return 0

    def _set_field_error(self, bad):
        self.find_field.setProperty('invalid', 'true' if bad else 'false')
        self.find_field.style().unpolish(self.find_field)
        self.find_field.style().polish(self.find_field)

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
            self.keep_cursor_clear()
        finally:
            self._searching = False
        self._paint()

    # -- replacing --------------------------------------------------------

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

    # -- highlighting -----------------------------------------------------

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


class GotoLineOverlay(EditorOverlay):
    """Jump to a line number, dropped from the top centre of the editor."""

    def __init__(self, editor, ce_widget=None):
        super(GotoLineOverlay, self).__init__(editor)
        self.ce_widget = ce_widget
        # Where the cursor was when the panel opened, to go back to on Esc
        # after the preview has scrolled away.
        self.return_position = 0

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(2)
        self.setLayout(layout)

        self.field = OverlayLineEdit(editor, parent=self)
        self.field.setFont(FONTS.monospace_font(9))
        self.field.setFixedWidth(180)
        self.field.setValidator(QtGui.QIntValidator(1, 1, self))
        self.field.textChanged.connect(self.preview)
        self.field.accepted.connect(self.accept)
        self.field.dismissed.connect(self.cancel)
        layout.addWidget(self.field)

        self.hint = QtWidgets.QLabel('', parent=self)
        self.hint.setFont(FONTS.monospace_font(8))
        layout.addWidget(self.hint)

    def overlay_position(self):
        x = (self.available_width() - self.width()) / 2
        return QtCore.QPoint(int(max(MARGIN, x)), MARGIN)

    def open_goto(self):
        last = self.editor.blockCount()
        self.return_position = self.editor.textCursor().position()
        self.field.setValidator(QtGui.QIntValidator(1, last, self))
        self.hint.setText('Go to line (1 - %d)' % last)
        self.field.clear()
        self.open_overlay()
        self.field.setFocus()

    def line_number(self):
        """The line typed in, or None if it is not a usable one.

        :rtype: int | None
        """
        text = self.field.text().strip()
        if not text.isdigit():
            return None
        number = int(text)
        if 1 <= number <= self.editor.blockCount():
            return number
        return None

    def preview(self):
        """Scroll to the line as it is typed, the way VS Code does."""
        number = self.line_number()
        if number is None:
            if self.field.text().strip():
                self.hint.setText('Line 1 - %d' % self.editor.blockCount())
            return
        self.hint.setText('Go to line (1 - %d)' % self.editor.blockCount())
        self.go_to(number)

    def go_to(self, number):
        block = self.editor.document().findBlockByNumber(number - 1)
        cursor = self.editor.textCursor()
        cursor.setPosition(block.position())
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()

    def accept(self):
        number = self.line_number()
        if number is not None:
            self.go_to(number)
        self.close_overlay()

    def cancel(self):
        """Put the cursor back where it was before the preview moved it."""
        cursor = self.editor.textCursor()
        position = min(self.return_position,
                       self.editor.document().characterCount() - 1)
        cursor.setPosition(max(0, position))
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.close_overlay()
