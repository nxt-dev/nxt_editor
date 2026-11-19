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


#: The modifiers, in the order a hotkey names them.
MODIFIERS = ((QtCore.Qt.ControlModifier, 'Ctrl'),
             (QtCore.Qt.ShiftModifier, 'Shift'),
             (QtCore.Qt.AltModifier, 'Alt'),
             (QtCore.Qt.MetaModifier, 'Meta'))
MODIFIER_KEYS = (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift,
                 QtCore.Qt.Key_Alt, QtCore.Qt.Key_Meta,
                 QtCore.Qt.Key_AltGr)


def held(modifiers):
    """The names of the modifiers held, Ctrl first."""
    return [name for modifier, name in MODIFIERS if modifiers & modifier]


def sequence_text(key, modifiers):
    """The hotkey a key pressed with modifiers makes, as text. Put
    together from names: adding modifier flags to a key's number crashes
    some PySide6 versions."""
    key_name = QtGui.QKeySequence(int(key)).toString(FORMAT)
    return '+'.join(held(modifiers) + [key_name])


def modifiers_text(modifiers):
    """The modifiers held so far, as Ctrl+Shift+, while waiting for the
    key that goes with them."""
    names = held(modifiers)
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
        # Every key is the field's while it records, none for the list
        # under it to act on.
        event.accept()
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
        self.recording = False
        self.setText(text)
        # Told once Qt is done with this key: what it sets off hides the
        # field, and the hotkey being changed is one Qt is matching keys to.
        QtCore.QTimer.singleShot(0, lambda: self.recorded.emit(text))

    def keyReleaseEvent(self, event):
        event.accept()
        if self.recording and event.key() in MODIFIER_KEYS:
            self.setText(modifiers_text(event.modifiers()))


class HotkeyEntry(object):
    """One action's hotkey: what it is, its default, and setting it."""

    def __init__(self, hotkeys, group, action):
        self.hotkeys = hotkeys
        self.group = group
        self.action = action
        self.title = action.text()
        about = action.whatsThis() or ''
        if not about and action.toolTip() != action.text():
            about = action.toolTip()
        self.about = about
        self.is_global = is_global(action)

    def shortcut(self):
        return as_text(self.action.shortcut())

    def default(self):
        return as_text(self.action.default_shortcut)

    def is_default(self):
        return self.shortcut() == self.default()

    def matches(self, words):
        text = ' '.join((HOTKEYS, self.group, self.title, self.about,
                         self.shortcut(),
                         'global' if self.is_global else '')).lower()
        return all(word in text for word in words)

    def set(self, text, parent=None):
        """Give the action this hotkey, if no other action's hotkey is in
        the way, and save it.

        :return: whether it was set
        """
        clash = self.hotkeys.clash(self.action, text)
        if clash is not None:
            QtWidgets.QMessageBox.warning(
                parent, 'Hotkeys',
                '{} is the hotkey for {}{}.'.format(
                    text, clash.text(),
                    ', which is global' if is_global(clash) else '') +
                ('\n\nA global hotkey can not be the same as any other.'
                 if is_global(clash) or self.is_global else ''))
            return False
        # An empty sequence is no hotkey, saved as none.
        self.action.setShortcut(QtGui.QKeySequence(text), user_override=True)
        return True

    def clear(self, parent=None):
        return self.set('', parent)

    def reset(self, parent=None):
        return self.set(self.default(), parent)


class Hotkeys(object):
    """The editor's actions with hotkeys, and the rule for clashes."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.groups = main_window.get_hotkey_map()
        self.entries = [HotkeyEntry(self, group, row[4])
                        for group, rows in self.groups.items()
                        for row in rows]

    def actions(self):
        for entry in self.entries:
            yield entry.action

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


ENTRY_ROLE = QtCore.Qt.UserRole + 1


class HotkeyList(QtWidgets.QListView):
    """Every hotkey, in one list that draws only the rows on screen.

    Each action is a row: its name, Global when it is, what it does, its
    hotkey in a box, and Clear and Reset when they apply. The parts of the
    editor are headings between them. A box records keys in a text field
    put over it while it is clicked, the only widget a row ever has, so
    there are no widgets per row to make or lay out: all of them show at
    once.
    """
    ROW_HEIGHT = 52
    GROUP_HEIGHT = 40
    BOX_WIDTH = 220
    BUTTON_WIDTH = 52
    GAP = 12

    def __init__(self, hotkeys, parent=None):
        super(HotkeyList, self).__init__(parent)
        self.hotkeys = hotkeys
        self.words = ()
        self.recorder = None  # the field, while it records
        self.field = None
        self.recording_entry = None
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setStyleSheet('QListView {background: transparent;}')
        self.setItemDelegate(HotkeyDelegate(self))
        model = QtGui.QStandardItemModel(self)
        group = None
        for entry in hotkeys.entries:
            if entry.group != group:
                group = entry.group
                heading = QtGui.QStandardItem(group)
                heading.setData(None, ENTRY_ROLE)
                model.appendRow(heading)
            item = QtGui.QStandardItem(entry.title)
            item.setData(entry, ENTRY_ROLE)
            model.appendRow(item)
        self.setModel(model)
        self.fit_height()

    # Rows ----------------------------------------------------------------

    def entry(self, index):
        return index.data(ENTRY_ROLE) if index.isValid() else None

    def entries(self):
        model = self.model()
        return [model.index(row, 0).data(ENTRY_ROLE)
                for row in range(model.rowCount())
                if model.index(row, 0).data(ENTRY_ROLE) is not None]

    def index_of(self, entry):
        model = self.model()
        for row in range(model.rowCount()):
            if model.index(row, 0).data(ENTRY_ROLE) is entry:
                return model.index(row, 0)
        return QtCore.QModelIndex()

    def shown_entries(self):
        model = self.model()
        return [model.index(row, 0).data(ENTRY_ROLE)
                for row in range(model.rowCount())
                if not self.isRowHidden(row) and
                model.index(row, 0).data(ENTRY_ROLE) is not None]

    def fit_height(self):
        """As tall as its rows: the page scrolls, not the list."""
        model = self.model()
        height = 0
        for row in range(model.rowCount()):
            if self.isRowHidden(row):
                continue
            entry = model.index(row, 0).data(ENTRY_ROLE)
            height += self.ROW_HEIGHT if entry else self.GROUP_HEIGHT
        self.setFixedHeight(height + 2)

    def filter(self, words):
        """Show the rows the words are found in, and the headings over
        them, with the words marked.

        :return: how many hotkeys are shown
        :rtype: int
        """
        self.words = tuple(words)
        model = self.model()
        shown = 0
        heading_row, heading_shown = None, False
        for row in range(model.rowCount()):
            entry = model.index(row, 0).data(ENTRY_ROLE)
            if entry is None:
                if heading_row is not None:
                    self.setRowHidden(heading_row, not heading_shown)
                heading_row, heading_shown = row, False
                continue
            match = entry.matches(words)
            self.setRowHidden(row, not match)
            if match:
                shown += 1
                heading_shown = True
        if heading_row is not None:
            self.setRowHidden(heading_row, not heading_shown)
        self.fit_height()
        self.viewport().update()
        return shown

    # Parts of a row ------------------------------------------------------

    def part_rects(self, rect):
        """Where a row's box, Clear and Reset are drawn.

        :return: (box, clear, reset)
        """
        right = rect.right() - 4
        reset = QtCore.QRect(right - self.BUTTON_WIDTH, rect.top(),
                             self.BUTTON_WIDTH, rect.height())
        clear = reset.translated(-self.BUTTON_WIDTH - 4, 0)
        box = QtCore.QRect(clear.left() - self.GAP - self.BOX_WIDTH,
                           rect.center().y() - 15, self.BOX_WIDTH, 30)
        return box, clear, reset

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        entry = self.entry(index)
        if entry is None or event.button() != QtCore.Qt.LeftButton:
            return super(HotkeyList, self).mousePressEvent(event)
        box, clear, reset = self.part_rects(self.visualRect(index))
        if box.contains(event.pos()):
            self.start_recording(index)
        elif clear.contains(event.pos()) and entry.shortcut():
            entry.clear(self)
        elif reset.contains(event.pos()) and not entry.is_default():
            entry.reset(self)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        entry = self.entry(index)
        cursor = QtCore.Qt.ArrowCursor
        if entry is not None:
            box, clear, reset = self.part_rects(self.visualRect(index))
            if (box.contains(event.pos()) or
                    (clear.contains(event.pos()) and entry.shortcut()) or
                    (reset.contains(event.pos()) and not entry.is_default())):
                cursor = QtCore.Qt.PointingHandCursor
        self.viewport().setCursor(cursor)
        super(HotkeyList, self).mouseMoveEvent(event)

    def start_recording(self, index):
        """Put the field over the row's box that records the next keys.
        One field, kept and moved from row to row: one made and deleted
        for each would be gone while Qt was still giving it the key."""
        entry = self.entry(index)
        field = self.field
        if field is None:
            # On the list, over its rows, rather than in the viewport the
            # list draws and takes events in.
            field = ShortcutField('', self)
            field.recorded.connect(self.recorded)
            field.editingFinished.connect(self.stop_recording)
            self.field = field
        box, _clear, _reset = self.part_rects(self.visualRect(index))
        self.recording_entry = entry
        field.setKeySequence(entry.shortcut())
        field.setGeometry(box.translated(self.viewport().pos()))
        field.show()
        field.setFocus()
        self.recorder = field
        return field

    def recorded(self, text):
        entry = self.recording_entry
        self.stop_recording()
        if entry is not None and text != entry.shortcut():
            entry.set(text, self)
        self.viewport().update()

    def stop_recording(self):
        self.recorder = None
        self.recording_entry = None
        if self.field is not None and self.field.isVisible():
            self.field.hide()
        self.viewport().update()


class HotkeyDelegate(QtWidgets.QStyledItemDelegate):
    """Draws a heading or a hotkey row, the same in every host."""

    def __init__(self, view):
        super(HotkeyDelegate, self).__init__(view)
        self.view = view
        self.heading_font = theme.font(theme.TEXT_PX + 2,
                                       weight=QtGui.QFont.Medium)
        self.name_font = theme.font(theme.TEXT_PX, weight=QtGui.QFont.Medium)
        self.small_font = theme.font(theme.SMALL_PX)

    def sizeHint(self, option, index):
        entry = index.data(ENTRY_ROLE)
        return QtCore.QSize(option.rect.width() or 400,
                            self.view.ROW_HEIGHT if entry
                            else self.view.GROUP_HEIGHT)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        entry = index.data(ENTRY_ROLE)
        rect = option.rect
        if entry is None:
            painter.setFont(self.heading_font)
            painter.setPen(theme.color(theme.TEXT))
            painter.drawText(rect.adjusted(4, 12, 0, 0),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                             index.data())
            painter.restore()
            return
        box, clear, reset = self.view.part_rects(rect)
        words = self.view.words
        # Name, and Global beside it.
        left = rect.left() + 4
        text_width = box.left() - left - 16
        name_rect = QtCore.QRect(left, rect.top() + 8, text_width, 18)
        name_width = self.draw_text(painter, entry.title, name_rect,
                                    self.name_font, theme.TEXT, words)
        if entry.is_global:
            metrics = QtGui.QFontMetrics(self.small_font)
            pill = QtCore.QRectF(left + name_width + 8, rect.top() + 8,
                                 metrics.horizontalAdvance('Global') + 12, 18)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(theme.color(theme.ACCENT_DIM))
            painter.drawRoundedRect(pill, 4, 4)
            painter.setFont(self.small_font)
            painter.setPen(theme.color(theme.TEXT))
            painter.drawText(pill, QtCore.Qt.AlignCenter, 'Global')
        about_rect = QtCore.QRect(left, rect.top() + 28, text_width, 16)
        self.draw_text(painter, entry.about, about_rect, self.small_font,
                       theme.TEXT_DIM, words)
        # The box.
        shortcut = entry.shortcut()
        painter.setPen(QtGui.QPen(theme.color(theme.BORDER_STRONG), 1))
        painter.setBrush(theme.color(theme.INPUT))
        painter.drawRoundedRect(QtCore.QRectF(box).adjusted(0.5, 0.5, -0.5,
                                                            -0.5),
                                theme.RADIUS, theme.RADIUS)
        self.draw_text(painter, shortcut or 'None', box.adjusted(8, 0, -8, 0),
                       theme.font(theme.TEXT_PX),
                       theme.TEXT if shortcut else theme.TEXT_FAINT,
                       words if shortcut else ())
        # Clear and Reset, where they would do something.
        painter.setFont(theme.font(theme.TEXT_PX))
        painter.setPen(theme.color(theme.TEXT))
        if shortcut:
            painter.drawText(clear, QtCore.Qt.AlignCenter, 'Clear')
        if not entry.is_default():
            painter.drawText(reset, QtCore.Qt.AlignCenter, 'Reset')
        # The line under the row.
        painter.setPen(QtGui.QPen(theme.color(theme.BORDER), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(),
                         rect.bottom())
        painter.restore()

    def draw_text(self, painter, text, rect, font, color, words):
        """One line of text, shortened to fit, with words marked.

        :return: the width it took
        """
        metrics = QtGui.QFontMetrics(font)
        shown = metrics.elidedText(text, QtCore.Qt.ElideRight, rect.width())
        width = metrics.horizontalAdvance(shown)
        painter.setFont(font)
        align = QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft
        x = rect.left()
        if words:
            # Each word found, behind the text.
            lower = shown.lower()
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(theme.color(theme.ACCENT_STRONG))
            for word in words:
                start = lower.find(word)
                while start != -1 and word:
                    before = metrics.horizontalAdvance(shown[:start])
                    span = metrics.horizontalAdvance(
                        shown[start:start + len(word)])
                    painter.drawRect(QtCore.QRectF(
                        x + before, rect.center().y() - metrics.height() / 2,
                        span, metrics.height()))
                    start = lower.find(word, start + len(word))
        painter.setPen(theme.color(color))
        painter.drawText(rect, align, shown)
        return width
