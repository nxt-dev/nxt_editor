"""The Hotkeys section of Preferences: every action's keyboard shortcut.

Actions are listed by the part of the editor they work in, as the main
window's get_hotkey_map gives them. A shortcut is changed by clicking its
box and pressing the keys, and is saved straight away to the user's
hotkeys file, as other preferences are.

A global action works anywhere in the window, so its shortcut can not be
one any other action uses, and no other action can take a global one.
"""
# Builtin
import logging

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
import nxt_editor
from nxt_editor import theme
from nxt_editor.preference_editor import HOTKEYS, SettingRow

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

HOW_TO = ('Click a hotkey and press the keys you want, then stop typing. '
          'Global hotkeys work anywhere in the window, so no other hotkey '
          'can be the same as one.')
FORMAT = QtGui.QKeySequence.PortableText


def as_text(shortcut):
    """A shortcut as text, empty for none.

    :param shortcut: a QKeySequence, text or None
    :rtype: str
    """
    if isinstance(shortcut, QtGui.QKeySequence):
        return shortcut.toString(FORMAT)
    return str(shortcut or '')


def is_global(action):
    return action.shortcutContext() == QtCore.Qt.WindowShortcut


MODIFIERS = ((QtCore.Qt.ControlModifier, QtCore.Qt.CTRL),
             (QtCore.Qt.ShiftModifier, QtCore.Qt.SHIFT),
             (QtCore.Qt.AltModifier, QtCore.Qt.ALT),
             (QtCore.Qt.MetaModifier, QtCore.Qt.META))
MODIFIER_KEYS = (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift,
                 QtCore.Qt.Key_Alt, QtCore.Qt.Key_Meta,
                 QtCore.Qt.Key_AltGr)


def sequence_text(key, modifiers):
    """The hotkey a key pressed with modifiers makes, as text."""
    code = int(key)
    for modifier, flag in MODIFIERS:
        if modifiers & modifier:
            code |= int(flag)
    return QtGui.QKeySequence(code).toString(FORMAT)


def modifiers_text(modifiers):
    """The modifiers held so far, as Ctrl+Shift+, while waiting for the
    key that goes with them."""
    names = [name for (modifier, _flag), name in
             zip(MODIFIERS, ('Ctrl', 'Shift', 'Alt', 'Meta'))
             if modifiers & modifier]
    return '+'.join(names) + ('+' if names else '')


class ShortcutField(QtWidgets.QLineEdit):
    """A hotkey's box. Clicked, it records the next key pressed with the
    modifiers held; Escape leaves it as it was."""
    recorded = QtCore.Signal(str)

    def __init__(self, shortcut, parent=None):
        super(ShortcutField, self).__init__(shortcut, parent)
        self.setReadOnly(True)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.setPlaceholderText('None')
        self.setToolTip('Click, then press the keys for this hotkey.')
        self.shown = shortcut
        self.recording = False

    def setKeySequence(self, sequence):
        self.shown = as_text(sequence)
        self.setText(self.shown)

    def focusInEvent(self, event):
        super(ShortcutField, self).focusInEvent(event)
        self.recording = True
        self.setText('')
        self.setPlaceholderText('Press keys...')

    def focusOutEvent(self, event):
        super(ShortcutField, self).focusOutEvent(event)
        self.recording = False
        self.setPlaceholderText('None')
        self.setText(self.shown)

    def event(self, event):
        # Keys pressed here are a hotkey being recorded, not one to use.
        # Asked before __init__ is done, while Qt sets the box up.
        if (getattr(self, 'recording', False) and
                event.type() == QtCore.QEvent.ShortcutOverride):
            event.accept()
            return True
        return super(ShortcutField, self).event(event)

    def keyPressEvent(self, event):
        if not self.recording or event.isAutoRepeat():
            return
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.clearFocus()
            return
        if key in MODIFIER_KEYS or key == QtCore.Qt.Key_unknown:
            self.setText(modifiers_text(event.modifiers()))
            return
        text = sequence_text(key, event.modifiers())
        self.clearFocus()
        self.recorded.emit(text)

    def keyReleaseEvent(self, event):
        if self.recording and event.key() in MODIFIER_KEYS:
            self.setText(modifiers_text(event.modifiers()))


class HotkeyRow(SettingRow):
    """One action's hotkey, with Clear and Reset."""

    def __init__(self, hotkeys, group, action, parent=None):
        self.hotkeys = hotkeys
        self.action = action
        self.section = HOTKEYS
        self.key = 'hotkey:{}:{}'.format(group, action.text())
        about = action.whatsThis() or ''
        if not about and action.toolTip() != action.text():
            about = action.toolTip()
        field = ShortcutField(as_text(action.shortcut()))
        field.recorded.connect(self.recorded)
        search = ' '.join((HOTKEYS, group, action.text(), about,
                           as_text(action.shortcut()),
                           'global' if is_global(action) else ''))
        super(HotkeyRow, self).__init__(
            action.text(), about, search, field,
            tag='Global' if is_global(action) else '', parent=parent)
        self.field = field
        self.clear_button = QtWidgets.QToolButton()
        self.clear_button.setText('Clear')
        self.clear_button.setToolTip('No hotkey for this action.')
        policy = self.clear_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.clear_button.setSizePolicy(policy)
        self.clear_button.clicked.connect(lambda _=False: self.set(''))
        self.extra.addWidget(self.clear_button)
        default = as_text(action.default_shortcut)
        self.reset_button.setToolTip(
            'Back to the default, {}.'.format(default or 'no hotkey'))
        self.reset_button.clicked.connect(
            lambda _=False: self.set(as_text(self.action.default_shortcut)))
        self.update_reset()

    def shortcut(self):
        return as_text(self.action.shortcut())

    def is_default(self):
        return self.shortcut() == as_text(self.action.default_shortcut)

    def update_reset(self):
        super(HotkeyRow, self).update_reset()
        self.clear_button.setVisible(bool(self.shortcut()))

    def recorded(self, text):
        if text == self.shortcut():
            return
        if not self.set(text):
            # Back to what it was.
            self.field.setKeySequence(QtGui.QKeySequence(self.shortcut()))

    def set(self, text):
        """Give the action this hotkey, if no other action's hotkey is in
        the way, and save it.

        :return: whether it was set
        """
        clash = self.hotkeys.clash(self.action, text)
        if clash is not None:
            QtWidgets.QMessageBox.warning(
                self, 'Hotkeys',
                '{} is the hotkey for {}{}.'.format(
                    text, clash.text(),
                    ', which is global' if is_global(clash) else '') +
                ('\n\nA global hotkey can not be the same as any other.'
                 if is_global(clash) or is_global(self.action) else ''))
            return False
        # An empty sequence is no hotkey, saved as none.
        self.action.setShortcut(QtGui.QKeySequence(text), user_override=True)
        self.field.setKeySequence(QtGui.QKeySequence(text))
        self.update_reset()
        return True


class Hotkeys(object):
    """The editor's actions with hotkeys, and the rule for clashes."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.groups = main_window.get_hotkey_map()

    def actions(self):
        for rows in self.groups.values():
            for row in rows:
                yield row[4]

    def clash(self, action, text):
        """The action whose hotkey is in the way of giving action text, or
        None. Only global hotkeys clash: one action's hotkey works where
        that part of the editor has focus, so two parts can share one.

        :rtype: QtWidgets.QAction | None
        """
        if not text:
            return None
        for other in self.actions():
            if other is action or as_text(other.shortcut()) != text:
                continue
            if is_global(other) or is_global(action):
                return other
        return None

    def rows_by_group(self, parent=None):
        """[(group name, [HotkeyRow])], in the editor's order."""
        result = []
        for group, rows in self.groups.items():
            result.append((group, [HotkeyRow(self, group, row[4], parent)
                                   for row in rows]))
        return result
