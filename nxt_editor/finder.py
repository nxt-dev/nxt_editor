"""Find Node, the box `/` opens in the graph.

It opens empty. Type a search, see node_search: names with * for anything
and commas between them. The nodes that match are listed as you type.
Pick one to select and frame it, or press Enter to select and frame every
one that matches.
"""
# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
from nxt_editor import node_search

# How long after the last key the nodes found are listed.
SEARCH_DELAY_MS = 300


class FinderLineEdit(QtWidgets.QLineEdit):

    focus_node = QtCore.Signal(str)

    def __init__(self, parent, node_paths=()):
        super(FinderLineEdit, self).__init__(parent)
        self.node_paths = list(node_paths)
        self.matches = []
        self.setPlaceholderText('Find nodes: arm*ctrl, leg')
        self.list_model = QtCore.QStringListModel(self)
        completer = QtWidgets.QCompleter(self.list_model, self)
        # The list is the search's own matches, shown as they are.
        completer.setCompletionMode(
            QtWidgets.QCompleter.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.activated.connect(self.focus_node.emit)
        # The row picked in the list, if any. Enter can reach the box
        # before the list says which row it took.
        self.highlighted_path = None
        completer.highlighted.connect(self.on_highlighted)
        completer.popup().setStyleSheet(parent.parent().stylesheet)
        self.setCompleter(completer)
        # Searched once typing stops, or on Enter, rather than on every
        # key.
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(
            lambda: self.update_matches(self.text()))
        self.textEdited.connect(lambda text: self.search_timer.start())
        self.returnPressed.connect(self.on_return)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def update_matches(self, text):
        """List the nodes the text finds."""
        search = node_search.search_for(text)
        self.matches = search.filter(self.node_paths) if search else []
        self.highlighted_path = None
        self.list_model.setStringList(self.matches)
        completer = self.completer()
        if self.matches:
            completer.complete()
        else:
            completer.popup().hide()

    def on_highlighted(self, node_path):
        self.highlighted_path = node_path or None

    def on_return(self):
        """Enter takes the row picked in the list, or every match."""
        if self.search_timer.isActive():
            self.search_timer.stop()
            self.update_matches(self.text())
        self.focus_node.emit(self.highlighted_path or '')

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
        self.done = False
        self.setFixedHeight(64)
        self.setFixedWidth(320)
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
        # Empty: the / that opened it is not part of the search.
        self.line_edit.setText('')
        self.line_edit.setFocus()

    def select_and_frame(self, node_path=None):
        """Select and frame node_path, or every node the search found."""
        # Picking a row with Enter can also send the Enter on to the box.
        if self.done:
            return
        self.done = True
        if node_path:
            paths = [node_path]
        else:
            paths = list(self.line_edit.matches)
        # After Qt is done with the key that picked: closing the box under
        # the list while it still handles the key crashed.
        QtCore.QTimer.singleShot(0, lambda: self.finish(paths))

    def finish(self, paths):
        if paths:
            self.stage_model.select_and_frame_nodes(paths)
        self.close()
