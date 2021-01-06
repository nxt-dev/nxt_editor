""" Dialogs. They're too small to deserve their own files.
"""
# Built-in
import logging
import os

# External
from Qt import QtCore, QtWidgets, QtGui

# Internal
import nxt_editor
from nxt_editor import user_dir

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class FilePathPrefEditor(QtWidgets.QDialog):
    """A dialog that defaults to existing value for a given preference key,
    provides a interface to pick a new file, and holds a value until
    user confirms intention to set the preference, when that preference
    is saved with the user's chosen value.
    """
    def __init__(self, pref_key, file_filter="*"):
        super(FilePathPrefEditor, self).__init__()
        self.pref_key = pref_key
        self.file_filter = file_filter
        self.default_file = None  # populated in self.populate
        self.layout = QtWidgets.QVBoxLayout(self)
        self.line_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.line_layout)

        pixmap = QtGui.QPixmap(':icons/icons/copy_resolved_12.png')
        icon = QtGui.QIcon(pixmap)
        self.file_button = QtWidgets.QPushButton(icon, '')
        self.file_button.released.connect(self.choose_file)
        self.line_layout.addWidget(self.file_button)
        self.line_edit = QtWidgets.QLineEdit('')
        self.line_layout.addWidget(self.line_edit)

        self.buttons_layout = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.buttons_layout)

        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.cancel_button.released.connect(self.close)
        self.buttons_layout.addWidget(self.cancel_button)

        self.save_button = QtWidgets.QPushButton('Save')
        self.save_button.setDefault(True)
        self.save_button.released.connect(self.save_pressed)
        self.buttons_layout.addWidget(self.save_button)

        self.populate()

    def populate(self):
        self.default_file = user_dir.user_prefs.get(self.pref_key, '')
        self.line_edit.setText(self.default_file)

    def save_pressed(self):
        user_dir.user_prefs[self.pref_key] = str(self.line_edit.text())
        self.done(True)

    def choose_file(self):
        current_text = self.line_edit.text()
        dialog_dir = os.getcwd()
        if current_text:
            current_dir = os.path.dirname(current_text)
            if current_dir:
                dialog_dir = current_dir
        elif self.default_file:
            current_dir = os.path.dirname(self.default_file)
            if current_dir:
                dialog_dir = current_dir
        file_filter = self.file_filter
        chosen_file = QtWidgets.QFileDialog.getOpenFileName(filter=file_filter,
                                                            dir=dialog_dir)[0]
        if chosen_file:
            self.line_edit.setText(chosen_file)

    def exec_(self):
        self.populate()
        return super(FilePathPrefEditor, self).exec_()


class NxtFileDialog(QtWidgets.QDialog):
    def __init__(self, file_filter=("*.nxt", "*.nxtb"), caption=''):
        super(NxtFileDialog, self).__init__()
        self.filter = file_filter
        self.filter_string = " ".join(self.filter)
        self.dir = ''
        self._file_path = ''
        self.mode = 'open'
        self.caption = caption
        self.setWindowTitle("{} nxt layer".format(self.mode))
        self.modes = {'open': self._open,
                      'save': self._save}
        self.vb_main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.vb_main_layout)

        self.hb_file_browse = QtWidgets.QHBoxLayout()
        self.vb_main_layout.addLayout(self.hb_file_browse)
        # File path line edit
        self.l_file_path = QtWidgets.QLineEdit()
        self.l_file_path.setText(self.get_base_path(with_file_name=False))
        self.hb_file_browse.addWidget(self.l_file_path)
        # TODO: Get the completer to complete relative paths based on the
        #  self.dir path. Right now it starts completions from the file
        #  system root.
        self.fsm_file = QtWidgets.QFileSystemModel()
        self.fsm_file.setFilter(QtCore.QDir.AllDirs |
                                QtCore.QDir.NoDotAndDotDot |
                                QtCore.QDir.Files)
        self.fsm_file.setNameFilters(self.filter)
        self.fsm_file.setNameFilterDisables(False)
        self.fsm_file.setRootPath(self.dir)
        self.completer = QtWidgets.QCompleter()
        self.completer.setModel(self.fsm_file)
        self.idx = QtCore.QModelIndex(self.fsm_file.index(self.dir))
        self.l_file_path.setCompleter(self.completer)
        # Default file browser
        self.btn_browse = QtWidgets.QPushButton('Browse')
        self.btn_browse.clicked.connect(self.browse)
        self.hb_file_browse.addWidget(self.btn_browse)

        self.hb_options = QtWidgets.QHBoxLayout()
        self.vb_main_layout.addLayout(self.hb_options)
        self.pb_rel_path = QtWidgets.QPushButton('Convert to relative path')
        self.pb_rel_path.clicked.connect(self.convert_path)
        self.hb_options.addWidget(self.pb_rel_path)
        self.btn_accept = QtWidgets.QPushButton(self.mode.capitalize())
        self.btn_accept.setDefault(True)
        self.btn_accept.clicked.connect(self.accept)
        self.hb_options.addWidget(self.btn_accept)

    def get_file_path(self, base_dir, mode, **kwargs):
        if 'filter' in kwargs.keys():
            self.filter = kwargs['filter']
        if not base_dir:
            base_dir = os.getcwd()
        self.dir = base_dir
        self.mode = mode
        self.setWindowTitle("{} nxt layer".format(self.mode))
        if not os.path.isdir(self.dir):
            self.l_file_path.setText(self.dir)
        self.exec_()

    @classmethod
    def system_file_dialog(cls, base_dir=None, mode='open', **kwargs):
        fd = cls(caption=kwargs.get('caption', ''))
        if 'filter' in kwargs.keys():
            fd.filter = kwargs['filter']
        if not base_dir:
            base_dir = os.getcwd()
        fd.dir = base_dir
        fd.mode = mode
        fd.browse()
        return fd.file_path

    @classmethod
    def get_open_file_path(cls, base_dir=None, **kwargs):
        fd = cls()
        fd.get_file_path(base_dir, 'open', **kwargs)
        return fd.file_path

    @classmethod
    def get_save_file_path(cls, base_dir=None, **kwargs):
        fd = cls()
        fd.get_file_path(base_dir, 'save', **kwargs)
        return fd.file_path

    def browse(self):
        file_path = self.modes[self.mode]()
        self.file_path = file_path

    def get_base_path(self, with_file_name=True):
        line_text = self.l_file_path.text()
        base = None
        if line_text:
            base = os.path.basename(line_text)
        if not base and os.path.isdir(self.dir) and with_file_name:
            base = os.path.join(self.dir, 'untitled.nxt')
        else:
            base = self.dir
        return base

    def _open(self):
        # TODO: Make the options a user pref
        ff = self.filter_string
        base = self.get_base_path()
        caption = 'Open'
        if self.caption:
            caption = self.caption
        options = QtWidgets.QFileDialog.DontUseNativeDialog
        file_path = QtWidgets.QFileDialog.getOpenFileName(filter=ff,
                                                          dir=base,
                                                          caption=caption,
                                                          options=options)[0]
        if not os.path.isfile(file_path):
            return
        return file_path

    def _save(self):
        ff = self.filter_string
        base = self.get_base_path()
        caption = 'Save'
        if self.caption:
            caption = self.caption
        options = QtWidgets.QFileDialog.DontUseNativeDialog
        file_path = QtWidgets.QFileDialog.getSaveFileName(filter=ff,
                                                          dir=base,
                                                          caption=caption,
                                                          options=options)[0]
        if not os.path.isdir(os.path.dirname(file_path)):
            return
        return file_path

    @property
    def file_path(self):
        return self._file_path

    @file_path.setter
    def file_path(self, file_path=None):
        line_text = self.l_file_path.text()
        if not file_path and not line_text:
            self._file_path = None
            return
        if not file_path:
            file_path = line_text
        p, ext = os.path.splitext(file_path)
        if not ext:
            file_path += '.nxt'
        if line_text != file_path:
            self.l_file_path.setText(file_path)
        self._file_path = file_path

    def set_file_path(self):
        line_text = self.l_file_path.text()
        self.file_path = line_text

    def convert_path(self):
        input_path = self.l_file_path.text()
        common = os.path.commonprefix([self.dir, input_path])
        rel_path = os.path.relpath(input_path, common)
        result_file_path = rel_path
        self.file_path = result_file_path

    def accept(self):
        self.file_path = self.l_file_path.text()
        super(NxtFileDialog, self).accept()

    def reject(self):
        self._file_path = None
        super(NxtFileDialog, self).reject()


class NxtWarningDialog(QtWidgets.QDialog):
    def __init__(self, text, info, details=''):
        super(NxtWarningDialog, self).__init__()
        self.show_details = False
        self._detail_text = details
        self.build_widgets()
        self.setDetailedText(self._detail_text)
        self.setText(text)
        self.setInformativeText(info)
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)

    def build_widgets(self):
        self.icon = QtWidgets.QLabel("Pretend this is\nan icon")
        pixmap = QtGui.QPixmap(':icons/icons/nxt_err_128.png')
        self.icon.setPixmap(pixmap)
        self.text_label = QtWidgets.QLabel()
        self.text_label.setTextFormat(QtCore.Qt.RichText)
        self.info_label = QtWidgets.QLabel()
        self.show_details_button = QtWidgets.QPushButton("Show Details")
        self.show_details_button.released.connect(self.on_details_toggle)
        self.confirm_button = QtWidgets.QPushButton("Ok")
        self.confirm_button.setDefault(True)
        self.confirm_button.released.connect(self.close)

        self.details_text = QtWidgets.QLabel("Details")
        int_flags = (
            QtCore.Qt.TextSelectableByMouse |
            QtCore.Qt.TextSelectableByKeyboard
        )
        self.details_text.setTextInteractionFlags(int_flags)
        self.details_text.setFrameShape(QtWidgets.QFrame.Panel)
        self.details_text.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.details_text.setLineWidth(1)

        self.details_line = QtWidgets.QFrame()
        self.details_line.setFrameShape(QtWidgets.QFrame.HLine)
        self.details_line.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.copy_details_button = QtWidgets.QPushButton("Copy to clipboard")
        self.copy_details_button.released.connect(self.on_copy_details)

        self.save_details_button = QtWidgets.QPushButton("Save to file")
        self.save_details_button.released.connect(self.on_save_details)

        self.detail_buttons_layout = QtWidgets.QHBoxLayout()
        self.detail_buttons_layout.addStretch(streth=1)
        self.detail_buttons_layout.addWidget(self.save_details_button)
        self.detail_buttons_layout.addWidget(self.copy_details_button)

        self.details_layout = QtWidgets.QVBoxLayout()
        self.details_layout.addWidget(self.details_line)
        self.details_layout.addWidget(self.details_text)
        self.details_layout.addLayout(self.detail_buttons_layout)
        self.details_widget = QtWidgets.QWidget()
        self.details_widget.setLayout(self.details_layout)

        self.buttons_layout = QtWidgets.QHBoxLayout()
        self.buttons_layout.addWidget(self.show_details_button)
        self.buttons_layout.addWidget(self.confirm_button)
        self.top_right_layout = QtWidgets.QVBoxLayout()
        self.top_right_layout.addWidget(self.text_label)
        self.top_right_layout.addWidget(self.info_label)
        self.top_right_layout.addStretch(streth=1)
        self.top_right_layout.addLayout(self.buttons_layout)
        self.top_layout = QtWidgets.QHBoxLayout()
        self.top_layout.addWidget(self.icon)
        self.top_layout.addLayout(self.top_right_layout)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)
        self.main_layout.addLayout(self.top_layout)
        self.main_layout.addWidget(self.details_widget)

        self._update_details()

    def setText(self, text):
        bold = '<b>' + text + '</b>'
        self.text_label.setText(bold)

    def setDetailedText(self, details):
        self._detail_text = details
        self._update_details()

    def setInformativeText(self, text):
        self.info_label.setText(text)

    def on_details_toggle(self):
        self.show_details = not self.show_details
        self._update_details()

    def on_copy_details(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self._detail_text)

    def on_save_details(self):
        file_name = QtWidgets.QFileDialog.getSaveFileName()[0]
        _, ext = os.path.splitext(file_name)
        if not ext:
            file_name += '.txt'
        with open(file_name, 'w+') as fp:
            fp.write(self._detail_text)

    def _update_details(self):
        if self._detail_text:
            self.show_details_button.show()
            self.details_text.setText(self._detail_text)
        else:
            self.show_details_button.hide()
        if self.show_details:
            self.show_details_button.setText("Hide Details...")
            self.details_widget.show()
        else:
            self.show_details_button.setText("Show Details...")
            self.details_widget.hide()

    @classmethod
    def show_message(cls, text, info, details=None):
        dialog = cls(text=text, info=info, details=details)
        dialog.exec_()


class NxtConfirmDialog(QtWidgets.QMessageBox):
    def __init__(self, text='Title', info='Confirm something!',
                 button_text=None, icon=QtWidgets.QMessageBox.Icon.Question):
        """Simple message box used for user confirmation
        :param text: Title text
        :param info: Main info text
        :param button_text: Custom button text dict:
        {QtWidgets.QMessageBox.Ok: 'Custom Ok Text',
        QtWidgets.QMessageBox.Cancel: 'Custom Cancel Text'}
        """
        super(NxtConfirmDialog, self).__init__()
        self.setText(text)
        self.setInformativeText(info)
        self.setStandardButtons(self.Ok)
        self.setIcon(icon)
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.setStandardButtons(self.Ok | self.Cancel)
        if button_text:
            self.setButtonText(self.Ok, button_text.get(self.Ok, 'Ok'))
            self.setButtonText(self.Cancel, button_text.get(self.Cancel,
                                                            'Cancel'))

    @classmethod
    def show_message(cls, *args, **kwargs):
        """Class method for easily showing the dialog. If the user clicks the
        'ok' button True is returned otherwise False is returned.
        :param kwargs: See __init__
        :return: bool
        """
        dialog = cls(*args, **kwargs)
        result = dialog.exec_()
        if result == dialog.Ok:
            return True
        return False


class UnsavedLayersDialogue(QtWidgets.QDialog):
    @classmethod
    def save_before_exit(cls, stage_models, main_window):
        inst = cls(stage_models, main_window)
        return inst.exec_()

    def __init__(self, stage_models, main_window):
        self.main_window = main_window
        super(UnsavedLayersDialogue, self).__init__(parent=main_window)
        self.setWindowTitle('Unsaved layers')
        self.setWhatsThis('Please check the box next the layers you would like '
                          'to save.')
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)
        # Message Label
        message = ("The checkable layers below have unsaved changes.\n"
                   "Select layers to save.")
        self.message_label = QtWidgets.QLabel(message)
        self.main_layout.addWidget(self.message_label)
        # Unsaved Tree
        self.unsaved_tree = QtWidgets.QTreeView()
        self.unsaved_tree.setHeaderHidden(True)
        self.unsaved_model = self.make_unsaved_model(stage_models)
        self.unsaved_tree.setModel(self.unsaved_model)
        self.unsaved_tree.expandAll()
        self.main_layout.addWidget(self.unsaved_tree)
        # Response Buttons
        self.response_layout = QtWidgets.QHBoxLayout()
        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.cancel_button.released.connect(self.reject)
        self.response_layout.addWidget(self.cancel_button)
        self.save_button = QtWidgets.QPushButton('Save Checked and Close')
        self.save_button.released.connect(self.on_save_released)
        self.response_layout.addWidget(self.save_button)
        self.ignore_button = QtWidgets.QPushButton('Ignore and Close')
        self.ignore_button.released.connect(self.accept)
        self.response_layout.addWidget(self.ignore_button)
        self.main_layout.addLayout(self.response_layout)

    @staticmethod
    def make_unsaved_model(stage_models):
        model = QtGui.QStandardItemModel()

        def r_add(stage_model, layer, parent_item, dirty):
            item = QtGui.QStandardItem(layer.get_alias())
            item.setData(layer)
            item.setEditable(False)
            if layer in dirty:
                item.setCheckable(True)
                item.setCheckState(QtCore.Qt.Checked)
            color_code = stage_model.get_layer_color(layer)
            item.setBackground(QtGui.QBrush(QtGui.QColor(color_code)))
            item.setForeground(QtGui.QBrush(QtCore.Qt.white))
            parent_item.appendRow(item)
            for lay_dict in layer.sub_layers:
                r_add(stage_model, lay_dict['layer'], item, dirty)
        for s_m in stage_models:
            r_add(s_m, s_m.top_layer, model, s_m.get_unsaved_changes())
        return model

    def on_save_released(self):
        layers_to_save = []

        def save_checked(item):
            unsaved_layer = item.data()
            if item.checkState() == QtCore.Qt.Checked:
                layers_to_save.insert(0, unsaved_layer)
            for i in range(item.rowCount()):
                save_checked(item.child(i))
        for i in range(self.unsaved_model.rowCount()):
            save_checked(self.unsaved_model.item(i))
        for unsaved_layer in layers_to_save:
            self.main_window.save_layer(unsaved_layer)
        self.done(QtWidgets.QDialog.Accepted)


class UnsavedChangesMessage(QtWidgets.QMessageBox):
    @classmethod
    def save_before_close(cls, header=None, info=None):
        header = header or 'Unsaved changes detected.'
        message = cls()
        message.setWindowTitle('Unsaved Changes!')
        message.setText(header)
        info = info or 'Do you want to save your changes?'
        message.setInformativeText(info)
        message.setStandardButtons(message.Save |
                                   message.Discard |
                                   message.Cancel)
        message.setIcon(message.Warning)
        return message.exec_()
