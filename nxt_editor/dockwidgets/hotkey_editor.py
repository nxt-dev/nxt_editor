# Built-in
import logging

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
import nxt_editor
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt_editor import colors, dialogs

logger = logging.getLogger(nxt_editor.LOGGER_NAME)
TOOLTIP_INFO = ('<p style="font-size:12px;color:white;">'
                '<h3>How to:</h3>'
                '<ul>'
                '<li>'
                'To edit a hotkey double click a cell in the <b>Shortcut</b> '
                'column and press a key combination. </li><li>'
                'When you release the key(s) the hotkey is temporally stored.'
                '</li><li>'
                'When you are ready to apply your changes click the <b>Save</b>'
                ' changes button at the bottom of the widget. </li><li>'
                'To revert or remove a hotkey, right click the shortcut cell.'
                '</li></ul>'
                '<h3>Note:</h3>'
                'Actions with <span style="color:#dfdf16;">yellow</span> text '
                'are global and cannot have a shortcut that conflicts with any '
                'other shortcut.</p>')

TOOLTIP_STYLE = '''QToolTip {
                    font-family: Roboto Mono;
                    background-color: #3E3E3E;
                    border: 1px solid #232323;
                }'''

TABLE_STYLE = '''QTableView {
                    font-family: Roboto Mono;
                }'''


class HotkeyEditor(DockWidgetBase):
    savable = QtCore.Signal(bool)
    refresh = QtCore.Signal()

    def __init__(self, parent):
        super(HotkeyEditor, self).__init__('Hotkey Editor', parent,
                                           minimum_height=250)
        self.setWindowFlags(QtCore.Qt.Tool)
        self.main_window = parent
        self.main_widget = QtWidgets.QWidget(parent=self)
        self.setWidget(self.main_widget)

        self.layout = QtWidgets.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.main_widget.setLayout(self.layout)

        self.background_frame = QtWidgets.QFrame(self)
        self.layout.addWidget(self.background_frame)

        self.main_frame = QtWidgets.QFrame(self)
        self.layout.addWidget(self.main_frame)
        self.hotkey_layout = QtWidgets.QVBoxLayout()
        self.hotkey_layout.setContentsMargins(8, 0, 8, 0)
        self.hotkey_layout.setSpacing(0)
        self.main_frame.setLayout(self.hotkey_layout)
        self.hotkey_table_view = HotkeyView(self)
        self.hotkey_table_view.setToolTip(TOOLTIP_INFO)
        self.hotkey_table_view.horizontalHeader().setSectionsMovable(False)
        self.hotkey_table_view.horizontalHeader().setStretchLastSection(True)
        double_click = QtWidgets.QAbstractItemView.DoubleClicked
        self.hotkey_table_view.setEditTriggers(double_click)
        single_select = QtWidgets.QAbstractItemView.SingleSelection
        self.hotkey_table_view.setSelectionMode(single_select)
        self.hotkey_table_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.hotkey_table_view.customContextMenuRequested.connect(self.context_menu)

        self.hotkey_layout.addWidget(self.hotkey_table_view)
        self.hotkey_model = HotkeyModel(self, view=self.hotkey_table_view)
        self.hotkey_table_view.setModel(self.hotkey_model)
        self.hb_buttons = QtWidgets.QHBoxLayout()
        self.hotkey_layout.addLayout(self.hb_buttons)
        self.btn_discard = QtWidgets.QPushButton('Discard changes')
        self.btn_discard.setEnabled(False)

        def _discard():
            self.hotkey_model.discard_changes(warn=False)
        self.btn_discard.clicked.connect(_discard)
        self.savable.connect(self.btn_discard.setEnabled)
        self.hb_buttons.addWidget(self.btn_discard)
        self.btn_save = QtWidgets.QPushButton('Save & Apply changes')
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.hotkey_model.save)
        self.savable.connect(self.btn_save.setEnabled)
        self.hb_buttons.addWidget(self.btn_save)
        self.refresh.connect(self.hotkey_model.discard_changes)
        self.resize(self.hotkey_table_view.width()*8, self.minimumHeight())
        self.refresh.emit()

    def context_menu(self, pos):
        index = self.hotkey_table_view.indexAt(pos)
        self.hotkey_table_view.closePersistentEditor(index)
        if index.column() != len(self.hotkey_model.header_names)-1:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction('Revert Hotkey', self.revert_hotkey)
        menu.addAction('Remove Hotkey', self.remove_hotkey)
        menu.popup(QtGui.QCursor.pos())

    def revert_hotkey(self):
        index = self.hotkey_table_view.selectionModel().selectedIndexes()[0]
        self.hotkey_model.revert_hotkey(index)

    def remove_hotkey(self):
        index = self.hotkey_table_view.selectionModel().selectedIndexes()[0]
        self.hotkey_model.remove_hotkey(index)

    def closeEvent(self, event):
        allow = self.hotkey_model.discard_changes()
        if allow:
            return super(HotkeyEditor, self).closeEvent(event)
        return event.ignore()


class HotkeyModel(QtCore.QAbstractTableModel):
    def __init__(self, parent, view, headers=None):
        super(HotkeyModel, self).__init__()
        self.parent = parent
        self.header_names = headers or ['Name',
                                        'What\'s This', 'Tool Tip', 'Hotkey']
        self.view = view
        self.node_attr_names = list()
        self.attr_data = list()
        self.horizontal_header = self.view.horizontalHeader()
        self.state = None
        self.delegate = KeySequenceDelegate(parent=self)
        # set default data
        self._data = []
        self.user_changes = {}
        self.actions = {}
        self.cast_mode = QtGui.QKeySequence.PortableText
        self.protected_actions = []
        self.protected_shortcuts = []

    def discard_changes(self, warn=True):
        """Removes any changes made by the user.
        :param warn: If True a warning dialog will be shown allowing the user
        to cancel the discard.
        :return: False if user wants to cancel discard, True if user saved or
        discarded changes
        """
        if warn is True and self.user_changes.keys():
            info = 'Would you like to save your shortcuts?'
            resp = dialogs.UnsavedChangesMessage.save_before_close(info=info)
            save = dialogs.UnsavedChangesMessage.Save
            cancel = dialogs.UnsavedChangesMessage.Cancel
            if resp == cancel:
                return False
            elif resp == save:
                self.save()
        self.user_changes = {}
        self.update_data()
        self.parent.savable.emit(False)
        return True

    def update_data(self):
        nxt_hotkeys = self.parent.main_window.get_hotkey_map()
        self.clear()
        self.actions = {}
        self.protected_actions = []
        self.protected_shortcuts = []
        for section, widget_actions in nxt_hotkeys.items():
            # Div rows have a None object as their last item.
            div_row = [section, 'What\'s this', 'Tooltip', 'Shortcut', None]
            self._data.append(div_row)
            for action_data in widget_actions:
                action = action_data[4]
                self._data += [action_data]
                self.actions[action] = action.isEnabled()
                if action.shortcutContext() == QtCore.Qt.WindowShortcut:
                    self.protected_actions += [action]
                    self.protected_shortcuts += [action_data[3]]
        if nxt_hotkeys:
            fixed = QtWidgets.QHeaderView.Fixed
            self.horizontal_header.setSectionResizeMode(0, fixed)
            self.horizontal_header.setDefaultSectionSize(200)
            self.view.setItemDelegateForColumn(self.columnCount()-1,
                                               self.delegate)
            self.view.resizeRowsToContents()

    def update_protected_shortcuts(self, action, old_shortcut, new_shortcut):
        if action in self.protected_actions:
            if old_shortcut in self.protected_shortcuts:
                self.protected_shortcuts.remove(old_shortcut)
            if new_shortcut:
                self.protected_shortcuts += [new_shortcut]

    def clear(self):
        self.beginResetModel()
        self._data = []
        self.endResetModel()

    def save(self):
        for i, data in self.user_changes.items():
            shortcut, action = data
            action.setShortcut(shortcut, user_override=True)
        self.user_changes = {}
        self.update_data()
        self.parent.savable.emit(False)

    def revert_hotkey(self, index):
        row = index.row()
        action = self._data[row][self.columnCount()]
        old_value = self._data[row][3]
        value = action.default_shortcut
        if value == old_value:
            return
        if not self.valid_shortcut(action, value):
            self.show_invalid_message(value)
            return
        self.update_protected_shortcuts(action, old_value, value)
        self.setData(index, value, QtCore.Qt.EditRole)

    def valid_shortcut(self, action, shortcut):
        valid = True
        if action in self.protected_actions:
            if shortcut in self.all_shortcuts:
                valid = False
        elif shortcut in self.protected_shortcuts:
            valid = False
        return valid

    @staticmethod
    def show_invalid_message(shortcut):
        message = 'Invalid key sequence: {} \nIt would create a ' \
                  'conflict for a global shortcut'.format(shortcut)
        dialogs.NxtWarningDialog.show_message('Invalid shortcut!', message)

    def remove_hotkey(self, index):
        row = index.row()
        action = self._data[row][self.columnCount()]
        old_value = self._data[row][3]
        if not old_value:
            return
        self.update_protected_shortcuts(action, old_value, None)
        self.setData(index, None, QtCore.Qt.EditRole)

    def disable_actions(self):
        for action in self.actions.keys():
            action.setEnabled(False)

    def enable_actions(self):
        for action in self.actions.keys():
            action.setEnabled(self.actions[action])

    def data(self, index, role=None):
        if not index.isValid:
            return None
        row = index.row()
        column = index.column()
        if role == QtCore.Qt.DisplayRole:
            return self._data[row][column]
        elif role == QtCore.Qt.EditRole:
            # Disable all the actions so the user input doesn't trigger one
            # I tried an event filter but it didn't work on application
            # shortcuts like Ctrl+S
            self.disable_actions()
            return self._data[row][column]
        elif role == QtCore.Qt.ForegroundRole:
            action = self._data[row][self.columnCount()]
            if action and action.shortcutContext() == QtCore.Qt.WindowShortcut:
                color = colors.IMPORTANT
                return QtGui.QBrush(color)
        elif role == QtCore.Qt.BackgroundRole:
            if row in self.user_changes.keys():
                color = colors.UNSAVED
                return QtGui.QBrush(color, QtCore.Qt.BDiagPattern)
            actions = self._data[row][self.columnCount()]
            if not actions:
                # TODO: Better style management
                color = QtGui.QColor(QtCore.Qt.darkGray).darker(250)
                return QtGui.QBrush(color)
        elif role == QtCore.Qt.FontRole:
            action = self._data[row][self.columnCount()]
            if action:
                default_shortcut = action.default_shortcut
                if isinstance(default_shortcut, QtGui.QKeySequence):
                    default_shortcut = default_shortcut.toString()
                shortcut = self._data[row][self.columnCount()-1] or None
                if shortcut != default_shortcut:
                    font = QtGui.QFont()
                    font.setItalic(True)
                    return font
            else:
                font = QtGui.QFont()
                font.setBold(True)
                font.setPointSizeF(font.pointSize()*1.1)
                font.setItalic(True)
                return font
        elif not role:
            return self._data[row][column]

    def setData(self, index, value, role):
        value_set = False
        if not index.isValid:
            return value_set
        row = index.row()
        column = index.column()
        # Reset the actions to their previous enabled state

        if role == QtCore.Qt.EditRole and column == self.columnCount()-1:
            if value != self._data[row][column]:
                self._data[row][column] = value
                action = self._data[row][column+1]
                # The last visible column holds the shortcut the column
                # after this holds the NxtAction object actions are always
                # in a list
                self.user_changes[row] = [value, action]
                value_set = True
            if row in list(self.user_changes.keys()):
                action = self.user_changes[row][1]
                if value == action.shortcut().toString(self.cast_mode):
                    self.user_changes.pop(row)
            self.enable_actions()
        if self.user_changes.keys():
            self.parent.savable.emit(True)
        else:
            self.parent.savable.emit(False)
        self.view.update()
        return value_set

    def flags(self, index):
        column = index.column()
        if column == self.columnCount()-1:
            return QtCore.Qt.ItemIsEnabled | \
                   QtCore.Qt.ItemIsSelectable | \
                   QtCore.Qt.ItemIsEditable
        else:
            return QtCore.Qt.NoItemFlags

    def headerData(self, section, orientation, role):
        if orientation is QtCore.Qt.Horizontal:
            if role is QtCore.Qt.DisplayRole:
                return self.header_names[section]

    def rowCount(self, parent):
        return len(self._data)

    def columnCount(self, *args):
        return len(self.header_names)

    @property
    def all_shortcuts(self):
        shortcuts = []
        for row in self._data:
            if row[self.columnCount()]:
                shortcuts += [row[3]]
        return shortcuts


class HotkeyView(QtWidgets.QTableView):
    def __init__(self, parent):
        super(HotkeyView, self).__init__(parent=parent)
        self.hotkey_editor = parent
        style = self.parent().styleSheet() + TOOLTIP_STYLE + TABLE_STYLE
        self.setStyleSheet(style)


class KeySequenceDelegate(QtWidgets.QStyledItemDelegate):

    def __init__(self, parent):
        super(KeySequenceDelegate, self).__init__(parent=parent)
        self.hotkey_model = parent

    def createEditor(self, parent, option, index):
        last_col = self.hotkey_model.columnCount()
        action = self.hotkey_model._data[index.row()][last_col]
        valid_cell = bool(action)
        if not valid_cell:
            # Don't allow users to edit rows that don't have actions in them
            return
        line_edit = KeySequenceEdit(parent, index.data(), action,
                                    self.hotkey_model)
        return line_edit


class KeySequenceEdit(QtWidgets.QLineEdit):
    """
    Based on https://gist.github.com/blink1073/946df268c3685a3f443e
    """

    def __init__(self, parent, key_sequence, action, hotkey_model):
        super(KeySequenceEdit, self).__init__(parent)
        self.action = action
        self.parent = parent
        self.hotkey_model = hotkey_model
        self.setText(key_sequence)
        self.press_count = 0
        self.keys = set()
        self.modifiers = ['Meta', 'Ctrl', 'Alt', 'Shift']
        self.input_text = key_sequence
        self.installEventFilter(self)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.cast_mode = QtGui.QKeySequence.PortableText
        self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        key = event.key()
        self.press_count += 1

        if key == QtCore.Qt.Key_unknown:
            logger.error("Unknown key from a macro probably")
            return
        event_modifiers = event.modifiers()
        modifier_key_map = {QtCore.Qt.Key_Control: QtCore.Qt.CTRL,
                         QtCore.Qt.Key_Shift: QtCore.Qt.SHIFT,
                         QtCore.Qt.Key_Alt: QtCore.Qt.ALT,
                         QtCore.Qt.Key_Meta: QtCore.Qt.META}
        if key in list(modifier_key_map.keys()) and not len(self.keys):
            shift_held = bool(event_modifiers & QtCore.Qt.ShiftModifier)
            ctrl_held = bool(event_modifiers & QtCore.Qt.ControlModifier)
            alt_held = bool(event_modifiers & QtCore.Qt.AltModifier)
            meta_held = bool(event_modifiers & QtCore.Qt.MetaModifier)
            held_modifiers = [meta_held, ctrl_held, alt_held, shift_held]
            if sum(held_modifiers) > 1:
                text = ''
                for modifier, held in zip(self.modifiers, held_modifiers):
                    if held:
                        text += '{}+'.format(modifier)
                text = text[:-1]
            else:
                key = modifier_key_map[key]
                keySequence = QtGui.QKeySequence(key)
                text = keySequence.toString()
            if not isinstance(text, str):
                text = text.decode()
            self.setText(text)
            return
        else:
            if event_modifiers & QtCore.Qt.ShiftModifier:
                key += QtCore.Qt.SHIFT
            if event_modifiers & QtCore.Qt.ControlModifier:
                key += QtCore.Qt.CTRL
                self.press_count -= 1
            if event_modifiers & QtCore.Qt.AltModifier:
                key += QtCore.Qt.ALT
            if event_modifiers & QtCore.Qt.MetaModifier:
                key += QtCore.Qt.META

            self.keys.add(key)
        if len(self.keys) > 4:
            logger.error("Too many keys, max 4!")
            text = 'Too many keys, max 4!'
            self.keys = set()
            self.press_count = 0
        else:
            keySequence = QtGui.QKeySequence(*self.keys)
            text = keySequence.toString(self.cast_mode)
            for modifier in self.modifiers:
                if text.count(modifier) > 1:
                    text = 'Invalid key combo'
                    self.keys = set()
                    self.press_count = 0
        self.setText(text)
        event.accept()

    def keyReleaseEvent(self, event):
        self.press_count = 0
        self.keys = set()
        key_seq = QtWidgets.QShortcut(QtGui.QKeySequence(self.text()), self)
        keys = key_seq.key().toString()
        valid = self.hotkey_model.valid_shortcut(self.action, keys)
        if keys != self.text():
            logger.error('Invalid key sequence! \'{}\''.format(self.text()))
            self.setText(self.input_text)
        elif not valid:
            self.setText(self.input_text)
            self.hotkey_model.show_invalid_message(keys)
            return
        self.hotkey_model.update_protected_shortcuts(self.action,
                                                     self.input_text, keys)
        self.clearFocus()
        event.accept()

    def focusOutEvent(self, event):
        self.hotkey_model.enable_actions()
        super(KeySequenceEdit, self).focusOutEvent(event)
