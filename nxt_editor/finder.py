# Builtin
from functools import partial

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
from nxt.nxt_path import NODE_SEP


class FinderLineEdit(QtWidgets.QLineEdit):

    focus_node = QtCore.Signal(str)

    def __init__(self, parent, node_paths=()):
        super(FinderLineEdit, self).__init__(parent)
        completer = QtWidgets.QCompleter(node_paths, parent=self)
        completer.activated.connect(self.focus_node.emit)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.popup().setStyleSheet(parent.parent().stylesheet)
        self.returnPressed.connect(partial(self.focus_node.emit, None))
        self.setCompleter(completer)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def focusOutEvent(self, event):
        super(FinderLineEdit, self).focusOutEvent(event)
        self.parent().close()

    def keyPressEvent(self, event):
        super(FinderLineEdit, self).keyPressEvent(event)
        if event.key() == QtCore.Qt.Key_Escape:
            self.setText('')
            self.parent().close()


class FinderWidget(QtWidgets.QWidget):
    def __init__(self, parent, stage_model):
        super(FinderWidget, self).__init__(parent, QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.stage_model = stage_model
        self.setFixedHeight(64)
        self.setFixedWidth(256)
        self.layout = QtWidgets.QVBoxLayout(self)
        node_paths = self.stage_model.comp_layer.descendants(include_implied=1)
        # Could use nxt_layer.sort_node_data but its too slow
        node_paths = sorted(node_paths)
        self.line_edit = FinderLineEdit(self, node_paths)
        self.line_edit.focus_node.connect(self.select_and_frame)
        self.layout.addWidget(self.line_edit)
        self.line_edit.setStyleSheet(self.parent().stylesheet)

    def show(self):
        super(FinderWidget, self).show()
        global_pos = QtGui.QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        self.move(local_pos)
        self.line_edit.setFocus()
        self.line_edit.setText(NODE_SEP)
        self.line_edit.completer().setCompletionPrefix(NODE_SEP)
        self.line_edit.completer().complete()

    def select_and_frame(self, node_path=None):
        if not node_path:
            node_path = self.line_edit.text()
        if node_path:
            self.stage_model.select_and_frame(node_path)
        self.close()
