"""Options > AI Assistant > Memory: what the assistant remembers, and the
folders it may always read."""
# External
from Qt import QtCore, QtWidgets

# Internal
from nxt_editor.ai.memory import Memory

ID_ROLE = QtCore.Qt.UserRole


class MemoryPage(QtWidgets.QWidget):
    """Notes and folders, to add, change and remove."""
    changed = QtCore.Signal()

    def __init__(self, prefs=None, parent=None):
        super(MemoryPage, self).__init__(parent)
        self.memory = Memory(prefs)
        layout = QtWidgets.QVBoxLayout(self)

        notes_box = QtWidgets.QGroupBox('Remembered')
        notes_layout = QtWidgets.QVBoxLayout(notes_box)
        about = QtWidgets.QLabel(
            'Sent at the start of every chat. Ask the assistant to '
            'remember something and it adds a note here. Double click a '
            'note to change it.')
        about.setWordWrap(True)
        about.setStyleSheet('color: grey')
        notes_layout.addWidget(about)
        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.setWordWrap(True)
        self.notes_list.itemChanged.connect(self.on_note_edited)
        self.notes_list.itemSelectionChanged.connect(self.update_buttons)
        notes_layout.addWidget(self.notes_list)
        row = QtWidgets.QHBoxLayout()
        self.add_note_button = QtWidgets.QPushButton('Add Note')
        self.add_note_button.clicked.connect(self.add_note)
        row.addWidget(self.add_note_button)
        self.remove_note_button = QtWidgets.QPushButton('Remove')
        self.remove_note_button.clicked.connect(self.remove_note)
        row.addWidget(self.remove_note_button)
        row.addStretch()
        notes_layout.addLayout(row)
        layout.addWidget(notes_box, 1)

        folders_box = QtWidgets.QGroupBox('Folders it can always read')
        folders_layout = QtWidgets.QVBoxLayout(folders_box)
        about = QtWidgets.QLabel(
            'The assistant asks before it reads files anywhere new. A '
            'folder you always allow is listed here, with what it holds, '
            'so later chats know to look there. The open graph\'s folder '
            'can always be read.')
        about.setWordWrap(True)
        about.setStyleSheet('color: grey')
        folders_layout.addWidget(about)
        self.folders_list = QtWidgets.QTreeWidget()
        self.folders_list.setHeaderLabels(['Folder', 'What it holds'])
        self.folders_list.setRootIsDecorated(False)
        self.folders_list.itemChanged.connect(self.on_folder_edited)
        self.folders_list.itemSelectionChanged.connect(self.update_buttons)
        self.folders_list.header().setStretchLastSection(True)
        # Only what a folder holds is changed here, by double clicking.
        self.folders_list.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.folders_list.itemDoubleClicked.connect(
            lambda item, _column: self.folders_list.editItem(item, 1))
        folders_layout.addWidget(self.folders_list)
        row = QtWidgets.QHBoxLayout()
        self.add_folder_button = QtWidgets.QPushButton('Add Folder...')
        self.add_folder_button.clicked.connect(self.add_folder)
        row.addWidget(self.add_folder_button)
        self.remove_folder_button = QtWidgets.QPushButton('Remove')
        self.remove_folder_button.clicked.connect(self.remove_folder)
        row.addWidget(self.remove_folder_button)
        row.addStretch()
        folders_layout.addLayout(row)
        layout.addWidget(folders_box, 1)
        self.refresh()

    def refresh(self):
        self.notes_list.blockSignals(True)
        self.notes_list.clear()
        for note in self.memory.notes():
            item = QtWidgets.QListWidgetItem(note['text'])
            item.setData(ID_ROLE, note['id'])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.notes_list.addItem(item)
        self.notes_list.blockSignals(False)
        self.folders_list.blockSignals(True)
        self.folders_list.clear()
        for folder in self.memory.folders():
            item = QtWidgets.QTreeWidgetItem([folder['path'],
                                              folder.get('about', '')])
            item.setData(0, ID_ROLE, folder['path'])
            item.setToolTip(0, folder['path'])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.folders_list.addTopLevelItem(item)
        self.folders_list.resizeColumnToContents(0)
        self.folders_list.blockSignals(False)
        self.update_buttons()

    def showEvent(self, event):
        super(MemoryPage, self).showEvent(event)
        # The assistant may have added to it since.
        self.refresh()

    def update_buttons(self):
        self.remove_note_button.setEnabled(
            bool(self.notes_list.selectedItems()))
        self.remove_folder_button.setEnabled(
            bool(self.folders_list.selectedItems()))

    # Notes
    def add_note(self):
        item = QtWidgets.QListWidgetItem('')
        item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
        self.notes_list.addItem(item)
        self.notes_list.setCurrentItem(item)
        self.notes_list.editItem(item)

    def on_note_edited(self, item):
        text = item.text().strip()
        note_id = item.data(ID_ROLE)
        if note_id:
            self.memory.update(note_id, text)
        elif text:
            self.memory.add(text)
        self.refresh()
        self.changed.emit()

    def remove_note(self):
        for item in self.notes_list.selectedItems():
            if item.data(ID_ROLE):
                self.memory.remove(item.data(ID_ROLE))
        self.refresh()
        self.changed.emit()

    # Folders
    def add_folder(self, path=None):
        if not path:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, 'A folder the assistant can always read')
        if path:
            self.memory.allow(path)
            self.refresh()
            self.changed.emit()

    def on_folder_edited(self, item, column):
        path = item.data(0, ID_ROLE)
        if column == 1:
            self.memory.set_about(path, item.text(1))
        self.refresh()
        self.changed.emit()

    def remove_folder(self):
        for item in self.folders_list.selectedItems():
            self.memory.disallow(item.data(0, ID_ROLE))
        self.refresh()
        self.changed.emit()
