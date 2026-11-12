# Builtin
import logging

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
import nxt_editor
from nxt import nxt_path
from nxt.nxt_layer import LayerReturnTypes
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

PATH_ROLE = QtCore.Qt.UserRole


def root_exec_order(model):
    """Every root node of the comp, in the order they run.

    Chains that begin at a start point come first, then the chains that
    don't. Each chain follows exec connections from its first node, and a
    node with more than one node after it runs those in their layer order.
    Roots that no chain reaches, such as a loop of exec connections, go
    last.

    :param model: StageModel
    :return: list of root node paths
    """
    layer = model.comp_layer
    # Roots have no saved order, the world node they would keep it on
    # doesn't exist, so they are taken in layer order.
    roots = layer.children(return_type=LayerReturnTypes.Path)
    root_set = set(roots)
    followers = {}
    heads = []
    for root in roots:
        exec_in = layer.get_exec_in(root)
        if exec_in in root_set and exec_in != root:
            followers.setdefault(exec_in, []).append(root)
        else:
            heads.append(root)
    starts = set(model.get_start_nodes())
    heads.sort(key=lambda path: path not in starts)
    order = []
    seen = set()

    def walk(path):
        if path in seen:
            return
        seen.add(path)
        order.append(path)
        for follower in followers.get(path, []):
            walk(follower)

    for head in heads:
        walk(head)
    for root in roots:
        walk(root)
    return order


class Outliner(DockWidgetBase):
    """The nodes of the graph as a tree.

    Root nodes are listed in the order they run, and each node's children
    sit under it in their child order. Selection follows the graph both
    ways, and double clicking a node frames it.
    """

    def __init__(self, parent=None):
        super(Outliner, self).__init__(title='Outliner', parent=parent,
                                       minimum_width=150)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        self.tree.itemDoubleClicked.connect(self.on_double_click)
        self.tree.itemCollapsed.connect(self.on_collapsed)
        self.tree.itemExpanded.connect(self.on_expanded)
        self.setWidget(self.tree)
        self.start_icon = QtGui.QIcon(
            QtGui.QPixmap(':icons/icons/add_startpoint.png'))
        self.items = {}
        # Paths the user closed, kept closed when the tree is rebuilt.
        self.collapsed = set()
        self._syncing = False
        # Several model signals can arrive for one edit, so the tree is
        # rebuilt once Qt is idle rather than for each of them.
        self.rebuild_timer = QtCore.QTimer(self)
        self.rebuild_timer.setSingleShot(True)
        self.rebuild_timer.setInterval(0)
        self.rebuild_timer.timeout.connect(self.rebuild)

    def set_stage_model(self, model):
        super(Outliner, self).set_stage_model(model)
        self.collapsed = set()
        self.request_rebuild()

    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.comp_layer_changed, self.request_rebuild),
            (model.nodes_changed, self.request_rebuild),
            (model.starts_changed, self.request_rebuild),
            (model.selection_changed, self.on_model_selection),
        ]
        super(Outliner, self).set_stage_model_connections(model, connect)

    def on_stage_model_destroyed(self):
        super(Outliner, self).on_stage_model_destroyed()
        self.rebuild_timer.stop()
        self.tree.clear()
        self.items = {}

    def request_rebuild(self, *args):
        # Hidden, there is nothing to draw. showEvent catches up.
        if self.isVisible():
            self.rebuild_timer.start()

    def showEvent(self, event):
        super(Outliner, self).showEvent(event)
        self.request_rebuild()

    def rebuild(self):
        model = self.stage_model
        self._syncing = True
        try:
            self.tree.clear()
            self.items = {}
            if not model:
                return
            starts = set(model.get_start_nodes())
            for root in root_exec_order(model):
                self.add_item(root, self.tree.invisibleRootItem(), starts)
            self.select_items(model.selection)
        finally:
            self._syncing = False

    def add_item(self, path, parent_item, starts):
        model = self.stage_model
        item = QtWidgets.QTreeWidgetItem(parent_item)
        item.setText(0, nxt_path.node_name_from_node_path(path))
        item.setToolTip(0, path)
        item.setData(0, PATH_ROLE, path)
        if path in starts:
            item.setIcon(0, self.start_icon)
        if not model.get_node_enabled(path):
            item.setForeground(0, QtGui.QBrush(QtGui.QColor('#808080')))
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
        self.items[path] = item
        for child in model.get_children(path, ordered=True):
            self.add_item(child, item, starts)
        item.setExpanded(path not in self.collapsed)
        return item

    def select_items(self, paths):
        self.tree.clearSelection()
        last = None
        for path in paths or ():
            item = self.items.get(path)
            if item is None:
                continue
            item.setSelected(True)
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            last = item
        if last is not None:
            self.tree.scrollToItem(last)

    def on_model_selection(self, paths):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.select_items(paths)
        finally:
            self._syncing = False

    def on_tree_selection(self):
        if self._syncing or not self.stage_model:
            return
        paths = [item.data(0, PATH_ROLE)
                 for item in self.tree.selectedItems()]
        self._syncing = True
        try:
            self.stage_model.set_selection(paths)
        finally:
            self._syncing = False

    def on_double_click(self, item, column=0):
        if self.stage_model:
            self.stage_model.select_and_frame(item.data(0, PATH_ROLE))

    def on_collapsed(self, item):
        self.collapsed.add(item.data(0, PATH_ROLE))

    def on_expanded(self, item):
        self.collapsed.discard(item.data(0, PATH_ROLE))
