"""CompletionController: the Controller of the completion MVC.

Glues the editor (a QPlainTextEdit) to the model and popup view. It builds a
CompletionContext from the cursor, queries the model (debounced for the jedi
code path so typing stays responsive), filters by prefix, and drives the
popup. Key handling for accept/navigate/dismiss is exposed for the editor.

The editor must provide:
    * textCursor(), toPlainText(), cursorRect(), viewport()  (QPlainTextEdit)
    * insert_completion(text, prefix)   -- replace the active prefix
    * set_completion_active(active)     -- toggle Tab/Enter edit actions
"""
from Qt import QtCore

from nxt_editor.completion.context import ContextKind, detect
from nxt_editor.completion.popup import CompletionPopup

_DEBOUNCE_MS = 120


class CompletionController(QtCore.QObject):
    """Orchestrates context detection, model queries and the popup view."""

    def __init__(self, editor, model, parent=None):
        super(CompletionController, self).__init__(parent or editor)
        self.editor = editor
        self.model = model
        self.popup = CompletionPopup(editor.viewport())
        self.popup.accepted.connect(self._on_popup_accepted)
        self._active_prefix = ''
        self._pending_prefix = ''
        self._debounce = QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._on_debounce)

    def popup_visible(self):
        return self.popup.isVisible()

    # -- request flow -------------------------------------------------- #
    def request(self, force=False):
        """Compute a context for the cursor and show completions for it.
        :param force: True when explicitly requested (Ctrl+Space), the jedi
        debounce is skipped.
        """
        context = self._build_context()
        if context.kind is ContextKind.NONE:
            self.dismiss()
            return
        self._pending_prefix = context.prefix
        # Debounce the jedi code path; tokens/fallback are cheap -> immediate.
        if (context.kind is ContextKind.CODE and self.model.jedi_enabled
                and not force):
            self._debounce.start()
        else:
            self._show_for(context)

    def _on_debounce(self):
        context = self._build_context()
        # Drop stale requests if the cursor moved off the queued prefix.
        if (context.kind is not ContextKind.CODE or
                context.prefix != self._pending_prefix):
            return
        self._show_for(context)

    def _show_for(self, context):
        names = self._rank(self.model.candidates(context), context.prefix)
        if not names or (len(names) == 1 and names[0] == context.prefix):
            self.dismiss()
            return
        self._active_prefix = context.prefix
        self.popup.show_items(names, self.editor.cursorRect(),
                              self.editor.viewport().height())
        self.editor.set_completion_active(True)

    # -- key handling -------------------------------------------------- #
    def handle_key_press(self, event):
        """Consume nav/accept/dismiss keys while the popup is up.
        :return: True if the event was handled.
        """
        if not self.popup.isVisible():
            return False
        key = event.key()
        if key in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return,
                   QtCore.Qt.Key_Tab):
            self.accept()
            return True
        if key in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Backtab):
            self.dismiss()
            return True
        if key in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down,
                   QtCore.Qt.Key_PageUp, QtCore.Qt.Key_PageDown):
            self.popup.move_selection(key)
            return True
        return False

    def accept(self):
        text = self.popup.current_text()
        if text:
            self.editor.insert_completion(text, self._active_prefix)
        self.dismiss()

    def dismiss(self):
        self._debounce.stop()
        self.popup.hide()
        self.editor.set_completion_active(False)

    # -- internals ----------------------------------------------------- #
    def _on_popup_accepted(self, text):
        if text:
            self.editor.insert_completion(text, self._active_prefix)
        self.dismiss()

    def _build_context(self):
        cursor = self.editor.textCursor()
        line = cursor.blockNumber() + 1
        column = cursor.positionInBlock()
        source = self.editor.toPlainText()
        return detect(source, line, column,
                      jedi_enabled=self.model.jedi_enabled)

    @staticmethod
    def _rank(names, prefix):
        """Filter by prefix and order by relevance (best match first)."""
        if not prefix:
            # No prefix: just keep underscores out of the way.
            return sorted(names, key=lambda n: (n.startswith('_'), n.lower()))
        low = prefix.lower()
        matches = [n for n in names if n.lower().startswith(low)]
        return sorted(matches, key=lambda n: (
            not n.startswith(prefix),   # exact case prefix matches first
            n.startswith('_'),          # underscore names last
            len(n),                     # shorter (closer) names first
            n.lower(),                  # alphabetical tiebreak
        ))
