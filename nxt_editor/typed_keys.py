"""Letting a list take the letters typed into it before window shortcuts.

Typing in a table or tree jumps to the row starting with what was typed.
Several window wide shortcuts are plain letters, though: Q, W and E switch
between the Raw, Resolved and Cached views, from anywhere in the window.
Qt offers a key to the shortcuts before the widget with focus, so typing
"wei" into the Property Editor's attribute table to find "weight" switched
to the Resolved view instead.

Before a shortcut fires, Qt asks the widget with focus whether it wants
the key itself, with a ShortcutOverride event. Line edits and text edits
say yes to the keys that type, which is why typing in them never set off a
shortcut. Lists do not, so wants_typed_key says yes for them.

Shortcuts that belong to the list itself, or to the panel it is in, still
win: they were put there for while it has focus.
"""
# External
from Qt import QtCore, QtGui

#: Holding any of these makes a key a shortcut rather than typing.
SHORTCUT_MODIFIERS = (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier |
                      QtCore.Qt.MetaModifier)


def is_typing(event):
    """Whether a key event types a character: a printable one, with no
    Ctrl, Alt or Meta held. Shift is fine, it types capitals.

    :param event: QKeyEvent
    :rtype: bool
    """
    if event.modifiers() & SHORTCUT_MODIFIERS:
        return False
    text = event.text()
    return bool(text) and text.isprintable()


def key_sequence(event):
    """The key event as a QKeySequence, to compare with shortcuts.

    :param event: QKeyEvent
    :rtype: QtGui.QKeySequence
    """
    try:
        return QtGui.QKeySequence(event.keyCombination())
    except AttributeError:
        # Qt 5 has no key combinations, a key and modifiers OR together.
        return QtGui.QKeySequence(int(event.modifiers()) | event.key())


def has_own_shortcut(widget, event):
    """Whether one of widget's own actions, or one of the panels it is
    in, is set off by the key. Those are meant for while it has focus.

    :param widget: QWidget with focus
    :param event: QKeyEvent
    :rtype: bool
    """
    sequence = key_sequence(event)
    owner = widget
    while owner is not None:
        for action in owner.actions():
            if not action.isEnabled():
                continue
            context = action.shortcutContext()
            if owner is not widget and context == QtCore.Qt.WidgetShortcut:
                # Only for while that one widget has focus.
                continue
            if context not in (QtCore.Qt.WidgetShortcut,
                               QtCore.Qt.WidgetWithChildrenShortcut):
                continue
            for shortcut in action.shortcuts():
                if (shortcut.matches(sequence) ==
                        QtGui.QKeySequence.ExactMatch):
                    return True
        if owner.isWindow():
            break
        owner = owner.parentWidget()
    return False


def wants_typed_key(widget, event):
    """Whether widget should keep a key from the window's shortcuts. Call
    it from a widget's event() with the ShortcutOverride event, and accept
    the event when it says yes.

    :param widget: QWidget with focus
    :param event: QKeyEvent, a ShortcutOverride
    :rtype: bool
    """
    if event.type() != QtCore.QEvent.ShortcutOverride:
        return False
    return is_typing(event) and not has_own_shortcut(widget, event)
