"""Edit > Preferences > Environment Variables: editing nxt's env files.

nxt sets environment variables from env files as it starts, see
nxt.env_files. This is where they are edited without opening json: the
user's own file, the site's, any named in NXT_ENV_FILES, and project files,
which are env files kept beside a project, under version control, that the
user's file includes.

Nothing is written until OK or Apply. Then the changed files are saved and
applied to this session, so a graph opened or reloaded afterwards resolves
with the new values.
"""
# Builtin
import logging
import os
from collections import OrderedDict

# External
from Qt import QtWidgets, QtCore

# Internal
from nxt_editor import theme
try:
    from nxt import env_files
except ImportError:
    # An nxt core from before env files. The menu item is hidden.
    env_files = None

logger = logging.getLogger(__name__)

#: Between the paths of a list value, on every platform. The file holds
#: them as a list, and nxt joins that with the platform's own separator.
VALUE_SEP = ';'
NAME_COL, LIST_COL, VALUE_COL, NOW_COL = range(4)
FILE_FILTER = 'nxt env file (*.json)'
#: Names that hold several paths without saying so in their name.
PATH_LIST_NAMES = ('NXT_FILE_ROOTS',)


def available():
    """Whether the nxt core in use knows about env files."""
    return env_files is not None and hasattr(env_files, 'is_applied')


def holds_paths(name):
    """Whether a variable is one that holds several paths, like PATH.

    Only the List box's starting state for a new row. Any value can be
    made a list, or not, by ticking it.
    """
    name = name.strip().upper()
    return (name in PATH_LIST_NAMES or name.endswith('PATH') or
            name.endswith('_PATHS') or name.endswith('_ROOTS'))


def value_to_text(value):
    """A value as it is typed: a list's items with ; between them."""
    if isinstance(value, list):
        return (VALUE_SEP + ' ').join(value)
    return value


def text_to_value(text, as_list=False):
    """What is typed, as the file holds it.

    :param as_list: split at each ; into a list, which nxt joins with the
        platform's path separator. Otherwise the text is kept whole, ;
        and all.
    """
    if as_list:
        return [part.strip() for part in text.split(VALUE_SEP)
                if part.strip()]
    return text.strip()


def portable_path(path, env_file):
    """A path as it is best written in an env file.

    Under the file's own folder it is written from $NXT_ENV_FILE_DIR, so
    the file and what it points at can move, or be checked out somewhere
    else, together.
    """
    path = os.path.abspath(path).replace(os.sep, '/')
    folder = env_file.directory

    def comparable(text):
        # normcase turns the slashes back on Windows.
        return os.path.normcase(text).replace(os.sep, '/')

    if comparable(path) == comparable(folder):
        return '$' + env_files.FILE_DIR_VAR
    if comparable(path).startswith(comparable(folder) + '/'):
        return '$' + env_files.FILE_DIR_VAR + path[len(folder):]
    return path


# Room around a column title, on top of the width of its text.
HEADER_PADDING = 36


class EnvFilesDialog(QtWidgets.QDialog):
    """The env files nxt reads, one at a time, as a table of variables."""
    applied = QtCore.Signal()

    def __init__(self, parent=None):
        super(EnvFilesDialog, self).__init__(parent)
        self.setWindowTitle('Environment Variables')
        self.resize(760, 420)
        self.files = OrderedDict()  # path: EnvFile, as edited here
        self.labels = {}
        self.dirty = set()
        self.current = None
        self._filling = False

        layout = QtWidgets.QVBoxLayout(self)
        self.intro = QtWidgets.QLabel(
            'Set when nxt starts, in the editor and in headless runs. A '
            'variable that is already set outside nxt is left alone. Use '
            '$NXT_ENV_FILE_DIR for the folder of the file. Tick List for '
            'a value of several paths, with ; between them.')
        self.intro.setTextFormat(QtCore.Qt.PlainText)
        self.intro.setWordWrap(True)
        self.intro.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        layout.addWidget(self.intro)

        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(QtWidgets.QLabel('File'))
        self.file_box = QtWidgets.QComboBox()
        self.file_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                    QtWidgets.QSizePolicy.Fixed)
        # Sized by its longest path, one file deep in a project made the
        # whole dialog as wide as that path.
        self.file_box.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.file_box.setMinimumContentsLength(30)
        self.file_box.currentIndexChanged.connect(self.on_file_chosen)
        file_row.addWidget(self.file_box)
        self.add_file_button = QtWidgets.QPushButton('Add Project File...')
        self.add_file_button.setToolTip(
            'An env file kept with a project. Pick one, or name a new one. '
            'Your own env file will include it.')
        self.add_file_button.clicked.connect(self.add_project_file)
        file_row.addWidget(self.add_file_button)
        self.remove_file_button = QtWidgets.QPushButton('Remove')
        self.remove_file_button.setToolTip(
            'Stop including this project file. The file itself is kept.')
        self.remove_file_button.clicked.connect(self.remove_project_file)
        file_row.addWidget(self.remove_file_button)
        layout.addLayout(file_row)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Name', 'List', 'Value',
                                              'In This Session'])
        self.table.horizontalHeaderItem(LIST_COL).setToolTip(
            'Several paths, with ; between them. Saved as a list and joined '
            'with the separator of the platform nxt runs on.')
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(NAME_COL,
                                    QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(LIST_COL,
                                    QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(VALUE_COL, QtWidgets.QHeaderView.Stretch)
        # With no rows these two are as wide as their titles alone, and in
        # a host whose style pads a header more than it says, the titles
        # were cut short.
        header.ensurePolished()
        header.setMinimumSectionSize(
            header.fontMetrics().horizontalAdvance('Name') + HEADER_PADDING)
        header.setSectionResizeMode(NOW_COL, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)

        row = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton('Add Variable')
        self.add_button.clicked.connect(self.add_variable)
        row.addWidget(self.add_button)
        self.remove_button = QtWidgets.QPushButton('Remove Variable')
        self.remove_button.clicked.connect(self.remove_variable)
        row.addWidget(self.remove_button)
        self.folder_button = QtWidgets.QPushButton('Add Folder To Value...')
        self.folder_button.setToolTip(
            'Browse for a folder and add it to the selected variable.')
        self.folder_button.clicked.connect(self.add_folder)
        row.addWidget(self.folder_button)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok |
            QtWidgets.QDialogButtonBox.Apply |
            QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.apply)
        layout.addWidget(buttons)

        self.load_files()

    # Files ---------------------------------------------------------------

    def user_file(self):
        return self.files[self.key(env_files.USER_ENV_FILE)]

    @staticmethod
    def key(path):
        return os.path.normcase(os.path.abspath(path))

    def add_file(self, path, label):
        """Take a file into the dialog, read from disk if it is there."""
        key = self.key(path)
        if key in self.files:
            return key
        env_file = None
        if os.path.isfile(path):
            try:
                env_file = env_files.EnvFile.load(path)
            except (env_files.EnvFileError, OSError) as error:
                logger.error('Env file not shown, it cannot be read: {}'
                             ''.format(error))
                return None
        self.files[key] = env_file or env_files.EnvFile(path)
        self.labels[key] = label
        return key

    def load_files(self):
        """Everything nxt reads at startup, and what the user's includes."""
        self.files.clear()
        self.labels.clear()
        self.dirty.clear()
        user = self.key(env_files.USER_ENV_FILE)
        for path in env_files.start_files():
            key = self.key(path)
            if key == user:
                label = 'User'
            elif key == self.key(env_files.SITE_ENV_FILE):
                label = 'Site'
            else:
                label = env_files.ENV_FILES_ENV_VAR
            self.add_file(path, label)
        for path in self.user_file().include_paths():
            self.add_file(path, 'Project')
        self.fill_file_box(select=user)

    def fill_file_box(self, select=None):
        select = select or self.current
        self._filling = True
        self.file_box.clear()
        for key, env_file in self.files.items():
            self.file_box.addItem('{}:  {}'.format(self.labels[key],
                                                   env_file.path), key)
        self._filling = False
        index = max(self.file_box.findData(select), 0)
        self.file_box.setCurrentIndex(index)
        self.on_file_chosen(index)

    def project_include(self, key):
        """How the user's file names a project file, or None if it does
        not include it."""
        user = self.user_file()
        for written, path in zip(user.include, user.include_paths()):
            if self.key(path) == key:
                return written
        return None

    def add_project_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Project Env File', '', FILE_FILTER, '',
            QtWidgets.QFileDialog.DontConfirmOverwrite)
        if path:
            self.include_project_file(path)

    def include_project_file(self, path):
        """Show a project file, and have the user's file include it."""
        key = self.add_file(path, 'Project')
        if key is None:
            return
        if self.project_include(key) is None and key != self.key(
                env_files.USER_ENV_FILE):
            user = self.user_file()
            user.include.append(os.path.abspath(path).replace(os.sep, '/'))
            self.dirty.add(self.key(user.path))
        if not os.path.isfile(path):
            self.dirty.add(key)
        self.fill_file_box(select=key)

    def remove_project_file(self):
        written = self.project_include(self.current)
        if written is None:
            return
        user = self.user_file()
        user.include.remove(written)
        self.dirty.add(self.key(user.path))
        self.dirty.discard(self.current)
        del self.files[self.current]
        self.fill_file_box(select=self.key(user.path))

    # Variables -----------------------------------------------------------

    def on_file_chosen(self, index):
        if self._filling:
            return
        self.current = self.file_box.itemData(index)
        self.remove_file_button.setEnabled(
            self.current is not None and
            self.project_include(self.current) is not None)
        self.fill_table()

    def fill_table(self):
        self._filling = True
        self.table.setRowCount(0)
        env_file = self.files.get(self.current)
        if env_file is not None:
            for name, value in env_file.variables.items():
                self.append_row(name, value_to_text(value),
                                isinstance(value, list))
        self._filling = False
        self.update_session_column()

    def append_row(self, name, text, as_list=False):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, NAME_COL, QtWidgets.QTableWidgetItem(name))
        is_list = QtWidgets.QTableWidgetItem('')
        is_list.setFlags(QtCore.Qt.ItemIsEnabled |
                         QtCore.Qt.ItemIsSelectable |
                         QtCore.Qt.ItemIsUserCheckable)
        is_list.setToolTip(self.table.horizontalHeaderItem(
            LIST_COL).toolTip())
        self.table.setItem(row, LIST_COL, is_list)
        self.set_list(row, as_list)
        self.table.setItem(row, VALUE_COL, QtWidgets.QTableWidgetItem(text))
        now = QtWidgets.QTableWidgetItem('')
        now.setFlags(now.flags() & ~QtCore.Qt.ItemIsEditable)
        self.table.setItem(row, NOW_COL, now)
        return row

    def is_list(self, row):
        return self.table.item(row, LIST_COL).checkState() == \
            QtCore.Qt.Checked

    def set_list(self, row, as_list):
        self.table.item(row, LIST_COL).setCheckState(
            QtCore.Qt.Checked if as_list else QtCore.Qt.Unchecked)

    def update_session_column(self):
        """What each variable holds right now, and whether nxt set it."""
        for row in range(self.table.rowCount()):
            name = self.table.item(row, NAME_COL).text().strip()
            item = self.table.item(row, NOW_COL)
            if not name or name not in os.environ:
                item.setText('')
                item.setToolTip('Not set in this session yet.')
            elif env_files.is_applied(name):
                item.setText(os.environ[name])
                item.setToolTip('Set by nxt from an env file.')
            else:
                item.setText('{}   (set outside nxt, left alone)'
                             ''.format(os.environ[name]))
                item.setToolTip('Already set when nxt started, so the env '
                                'files do not change it.')

    def read_table(self):
        """The table back into the file being shown."""
        env_file = self.files.get(self.current)
        if env_file is None:
            return
        variables = OrderedDict()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, NAME_COL).text().strip()
            if name:
                variables[name] = text_to_value(
                    self.table.item(row, VALUE_COL).text(),
                    self.is_list(row))
        if list(variables.items()) != list(env_file.variables.items()):
            env_file.variables = variables
            self.dirty.add(self.current)

    def on_item_changed(self, item):
        if self._filling or item.column() == NOW_COL:
            return
        row = item.row()
        if (item.column() == NAME_COL and
                not self.table.item(row, VALUE_COL).text().strip()):
            # A row being started: a name like PATH starts out a list.
            self._filling = True
            self.set_list(row, holds_paths(item.text()))
            self._filling = False
        self.read_table()
        self._filling = True
        self.update_session_column()
        self._filling = False

    def add_variable(self):
        self._filling = True
        row = self.append_row('', '')
        self._filling = False
        self.table.setCurrentCell(row, NAME_COL)
        self.table.editItem(self.table.item(row, NAME_COL))

    def remove_variable(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        self.read_table()

    def add_folder(self):
        row = self.table.currentRow()
        env_file = self.files.get(self.current)
        if row < 0 or env_file is None:
            return
        start = env_file.directory if os.path.isdir(env_file.directory) else ''
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Folder', start)
        if folder:
            self.add_path_to_row(row, folder)

    def add_path_to_row(self, row, path):
        item = self.table.item(row, VALUE_COL)
        path = portable_path(path, self.files[self.current])
        text = item.text().strip()
        if text:
            # A second path makes it a list, whatever its name.
            self._filling = True
            self.set_list(row, True)
            self._filling = False
        item.setText(text + VALUE_SEP + ' ' + path if text else path)

    # Saving --------------------------------------------------------------

    def apply(self):
        """Save what changed and bring this session in step with it.

        :return: False when a file could not be written
        :rtype: bool
        """
        self.read_table()
        for key in list(self.dirty):
            env_file = self.files.get(key)
            if env_file is None:
                self.dirty.discard(key)
                continue
            try:
                for name, value in env_file.variables.items():
                    env_files.EnvFile.clean_value(name, value, env_file.path)
                env_file.save()
            except (env_files.EnvFileError, OSError) as error:
                QtWidgets.QMessageBox.warning(
                    self, 'Environment Variables',
                    'Could not save {}\n\n{}'.format(env_file.path, error))
                return False
            self.dirty.discard(key)
        env_files.apply()
        self.update_session_column()
        self.applied.emit()
        return True

    def accept(self):
        if self.apply():
            super(EnvFilesDialog, self).accept()
