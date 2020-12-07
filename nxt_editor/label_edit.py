# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore


class LabelEdit(QtWidgets.QLabel):
    doubleClicked = QtCore.Signal()
    nameChangeRequested = QtCore.Signal(str)

    def __init__(self, *args, **kwargs):
        super(LabelEdit, self).__init__(*args, **kwargs)
        self.doubleClicked.connect(self.edit_text)
        self._read_only = False

    def setReadOnly(self, state):
        """Named this way to mimic Qt"""
        self._read_only = state

    def mouseDoubleClickEvent(self, event):
        if self._read_only:
            return
        if event.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()

    def edit_text(self):
        if self._read_only:
            return
        # get current name
        name = self.text()

        # get current geometry
        rect = self.rect()
        point = rect.topLeft()
        global_point = self.mapToGlobal(point)
        geometry = QtCore.QRect(global_point.x(), global_point.y() - 1, rect.width(), rect.height())

        # dialog
        dialog = NameEditDialog(name=name, geometry=geometry, parent=self)
        dialog.line_edit.setFont(self.font())
        dialog.exec_()

        # change name
        if dialog.result():
            self.nameChangeRequested.emit(dialog.value)


class NameEditDialog(QtWidgets.QDialog):
    """https://gist.github.com/justinfx/1951709"""

    def __init__(self, name='', geometry=None, parent=None):
        super(NameEditDialog, self).__init__(parent)
        self.setGeometry(geometry)
        self.setStyleSheet('background-color: #3E3E3E')
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | QtCore.Qt.Popup)

        # layout
        self.layout = QtWidgets.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # line edit
        self.line_edit = QtWidgets.QLineEdit(name, parent=self)
        self.line_edit.setFocus()
        self.line_edit.selectAll()
        self.line_edit.setStyleSheet('background-color: #232323')
        self.layout.addWidget(self.line_edit)

    @property
    def value(self):
        return self.line_edit.text()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.reject()
            self.done(0)
        elif event.key() == QtCore.Qt.Key_Return:
            self.accept()
            self.done(1)
        else:
            super(NameEditDialog, self).keyPressEvent(event)

    def closeEvent(self, event):
        self.accept()
        super(NameEditDialog, self).closeEvent(event)
