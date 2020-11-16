import os

from Qt import QtCore, QtWidgets, QtGui


class SearchLineEdit(QtWidgets.QLineEdit):

    file_chosen = QtCore.Signal()

    def __init__(self, parent=None):
        super(SearchLineEdit, self).__init__(parent)
        completer = QtWidgets.QCompleter(parent=self)
        model = QtWidgets.QFileSystemModel(completer)
        model.setNameFilters(['*.nxt', '*.nxtb'])
        model.setNameFilterDisables(False)
        completer.setModel(model)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setCompletionMode(completer.UnfilteredPopupCompletion)
        completer.popup().setStyleSheet(parent.parent().stylesheet)
        self.returnPressed.connect(self.file_chosen.emit)
        self.setCompleter(completer)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def focusOutEvent(self, event):
        super(SearchLineEdit, self).focusOutEvent(event)
        self.parent().close()

    def keyPressEvent(self, event):
        super(SearchLineEdit, self).keyPressEvent(event)
        if event.key() == QtCore.Qt.Key_Escape:
            self.setText('')
            self.file_chosen.emit()
            return
        if event.key() == QtCore.Qt.Key_Return:
            return
        if os.path.isdir(self.text()) and self.text()[-1] == os.path.sep:
            QtCore.QTimer.singleShot(0, self.completer().complete)

    def setText(self, text):
        super(SearchLineEdit, self).setText(text)
        self.completer().model().setRootPath(text)


class Searcher(QtWidgets.QDialog):
    def __init__(self, parent, width, default=''):
        super(Searcher, self).__init__(parent, QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFixedHeight(64)
        self.setFixedWidth(width)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.line_edit = SearchLineEdit(self)
        default = os.path.normcase(default)
        self.line_edit.setText(default)
        self.line_edit.setStyleSheet(self.parent().stylesheet)
        self.line_edit.file_chosen.connect(self.close)
        self.layout.addWidget(self.line_edit)

    @classmethod
    def get_open_file_path(cls, *args, **kwargs):
        inst = cls(*args, **kwargs)
        inst.exec_()
        return inst.line_edit.text()
