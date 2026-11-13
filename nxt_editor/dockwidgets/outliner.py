# Builtin
import logging
import re

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
import nxt_editor
from nxt import nxt_path
from nxt.nxt_layer import LayerReturnTypes
from nxt_editor import colors
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

PATH_ROLE = QtCore.Qt.UserRole
# The layer colors of a row, the strongest opinion first.
LAYERS_ROLE = QtCore.Qt.UserRole + 1
# A section heading's start node, or '' for the nodes in no build.
SECTION_ROLE = QtCore.Qt.UserRole + 2
# True on a row whose own name matches the search.
MATCH_ROLE = QtCore.Qt.UserRole + 3

NOT_IN_A_BUILD = 'Not in a build'


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
    order = []
    for _start, roots in build_sections(model):
        order += roots
    return order


def build_sections(model):
    """The root nodes, grouped by the build that runs them.

    A build is what runs from a start point: the root the start point is
    on, then each root its exec connections lead to. There is a section
    for each start point, in the order the start points come in the layer,
    and a last one for the roots no build reaches. A root two builds reach
    is listed under the first.

    :param model: StageModel
    :return: list of (start path or None, [root paths in run order])
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
    seen = set()

    def walk(path, into):
        if path in seen:
            return
        seen.add(path)
        into.append(path)
        for follower in followers.get(path, []):
            walk(follower, into)

    sections = []
    for start in model.get_start_nodes():
        run = []
        walk(nxt_path.get_root_path(start), run)
        if run:
            sections.append((start, run))
    rest = []
    for head in heads:
        walk(head, rest)
    for root in roots:
        walk(root, rest)
    if rest:
        sections.append((None, rest))
    return sections


def search_pattern(text):
    """A case insensitive regex from what was typed, or None for nothing.

    Text that is not a valid regex is searched for as it is, so typing a
    bracket on the way to something else does not stop the search.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return re.compile(text, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(text), re.IGNORECASE)


class NodeRowDelegate(QtWidgets.QStyledItemDelegate):
    """Draws a row the way its node looks in the graph.

    The row is filled with the color of the layer with the strongest
    opinion, and each weaker layer with an opinion adds a chip of its color
    at the right end, as on the node's title bar. Section headings are
    plain text.
    """
    CHIP = 14        # wide enough to tell the colors apart at a glance
    CHIP_GAP = 2

    def sizeHint(self, option, index):
        size = super(NodeRowDelegate, self).sizeHint(option, index)
        return QtCore.QSize(size.width(), max(size.height(), 22))

    def paint(self, painter, option, index):
        layer_colors = index.data(LAYERS_ROLE)
        if not layer_colors:
            super(NodeRowDelegate, self).paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(option.rect).adjusted(1, 1, -2, -1)
        top = QtGui.QColor(layer_colors[0])
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hovered = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        fill = top
        if hovered and not selected:
            fill = fill.lighter(120)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.fillPath(path, fill)
        # A chip for each weaker layer, the next strongest nearest the
        # name, inside the row's rounded corners.
        weaker = layer_colors[1:]
        step = self.CHIP + self.CHIP_GAP
        chips_width = len(weaker) * step
        painter.save()
        painter.setClipPath(path)
        x = rect.right()
        for color in weaker:
            x -= step
            painter.fillRect(QtCore.QRectF(x + self.CHIP_GAP, rect.top(),
                                           self.CHIP, rect.height()),
                             QtGui.QColor(color))
        painter.restore()
        if selected:
            painter.setPen(QtGui.QPen(colors.SELECTED, 1.5))
            painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75),
                                    4, 4)
        y = rect.center().y()
        # Icon and name.
        left = rect.left() + 10
        icon = index.data(QtCore.Qt.DecorationRole)
        if isinstance(icon, QtGui.QIcon) and not icon.isNull():
            size = 14
            icon.paint(painter, QtCore.QRect(int(left), int(y - size / 2),
                                             size, size))
            left += size + 4
        font = index.data(QtCore.Qt.FontRole) or option.font
        if index.data(MATCH_ROLE):
            font = QtGui.QFont(font)
            font.setBold(True)
        painter.setFont(font)
        brush = index.data(QtCore.Qt.ForegroundRole)
        painter.setPen(brush.color() if brush else QtGui.QColor('#f0f0f0'))
        text_rect = QtCore.QRectF(left, rect.top(),
                                  rect.right() - chips_width - 6 - left,
                                  rect.height())
        text = QtGui.QFontMetrics(font).elidedText(
            index.data(QtCore.Qt.DisplayRole) or '', QtCore.Qt.ElideRight,
            int(text_rect.width()))
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter, text)
        painter.restore()


class Outliner(DockWidgetBase):
    """The nodes of the graph as a tree.

    Root nodes are grouped by the build that runs them, one section for
    each start point and a last one for the rest, and listed in the order
    they run. Each node's children sit under it in their child order.
    Rows are drawn in the colors of the layers the node is on. Selection
    follows the graph both ways, double clicking a node frames it, and the
    search box finds nodes at any depth by a regex on their name.
    """

    def __init__(self, parent=None):
        super(Outliner, self).__init__(title='Outliner', parent=parent,
                                       minimum_width=150)
        main = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(main)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search nodes (regex)')
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip('Show the nodes whose name matches, and the '
                               'nodes above them. Enter frames the first '
                               'match.')
        self.search.textChanged.connect(self.request_rebuild)
        self.search.returnPressed.connect(self.frame_first_match)
        layout.addWidget(self.search)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setMouseTracking(True)
        self.tree.setItemDelegate(NodeRowDelegate(self.tree))
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        self.tree.itemDoubleClicked.connect(self.on_double_click)
        self.tree.itemCollapsed.connect(self.on_collapsed)
        self.tree.itemExpanded.connect(self.on_expanded)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        layout.addWidget(self.tree)
        self.main_window = parent
        self.setWidget(main)
        self.start_icon = QtGui.QIcon(
            QtGui.QPixmap(':icons/icons/add_startpoint.png'))
        self.items = {}
        self.sections = {}
        self.matches = []
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
            (model.layer_color_changed, self.request_rebuild),
            (model.selection_changed, self.on_model_selection),
        ]
        super(Outliner, self).set_stage_model_connections(model, connect)

    def on_stage_model_destroyed(self):
        super(Outliner, self).on_stage_model_destroyed()
        self.rebuild_timer.stop()
        self.tree.clear()
        self.items = {}
        self.sections = {}

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
            self.sections = {}
            self.matches = []
            if not model:
                return
            pattern = search_pattern(self.search.text())
            starts = set(model.get_start_nodes())
            for start, roots in build_sections(model):
                heading = self.add_section(start)
                for root in roots:
                    self.add_item(root, heading, starts, pattern)
                if not heading.childCount():
                    # Nothing in it matched the search.
                    self.tree.invisibleRootItem().removeChild(heading)
                    self.sections.pop(start or '', None)
            # Only once every row is in the tree: Qt ignores expanding a
            # row that is not in it yet.
            searching = pattern is not None
            for path, item in self.items.items():
                item.setExpanded(searching or path not in self.collapsed)
            self.select_items(model.selection)
        finally:
            self._syncing = False

    def add_section(self, start):
        item = QtWidgets.QTreeWidgetItem(self.tree)
        if start:
            item.setText(0, 'Build from ' +
                         nxt_path.node_name_from_node_path(start))
            item.setToolTip(0, 'What runs from the start point on ' + start)
            item.setIcon(0, self.start_icon)
        else:
            item.setText(0, NOT_IN_A_BUILD)
            item.setToolTip(0, 'Nodes no start point leads to')
        item.setData(0, SECTION_ROLE, start or '')
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, QtGui.QBrush(QtGui.QColor('#a6a6a6')))
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        item.setFirstColumnSpanned(True)
        item.setExpanded(True)
        self.sections[start or ''] = item
        return item

    def layer_colors(self, path):
        model = self.stage_model
        layers = model.get_layers_with_opinion(path, as_layers=True)
        found = [model.get_layer_color(layer) for layer in layers]
        found = [color for color in found if color]
        if not found:
            found = [model.get_node_color(path) or '#808080']
        return found

    def add_item(self, path, parent_item, starts, pattern=None):
        """Add a node's row and its children's, keeping only the rows that
        match the search, and the rows above them.

        :return: the row, or None when neither it nor anything under it
            matched
        """
        model = self.stage_model
        name = nxt_path.node_name_from_node_path(path)
        matched = pattern is None or bool(pattern.search(name))
        item = QtWidgets.QTreeWidgetItem()
        item.setText(0, name)
        item.setToolTip(0, path)
        item.setData(0, PATH_ROLE, path)
        item.setData(0, LAYERS_ROLE, self.layer_colors(path))
        if pattern is not None and matched:
            item.setData(0, MATCH_ROLE, True)
        if path in starts:
            item.setIcon(0, self.start_icon)
        if not model.get_node_enabled(path):
            item.setForeground(0, QtGui.QBrush(QtGui.QColor('#808080')))
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
        for child in model.get_children(path, ordered=True):
            self.add_item(child, item, starts, pattern)
        if not matched and not item.childCount():
            return None
        parent_item.addChild(item)
        self.items[path] = item
        if pattern is not None and matched:
            self.matches.append(path)
        return item

    def frame_first_match(self):
        """Select and frame the first node the search found."""
        if self.stage_model and self.matches:
            self.stage_model.select_and_frame(self.matches[0])

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
        paths = [path for path in paths if path]
        self._syncing = True
        try:
            self.stage_model.set_selection(paths)
        finally:
            self._syncing = False

    def on_double_click(self, item, column=0):
        path = item.data(0, PATH_ROLE)
        if self.stage_model and path:
            self.stage_model.select_and_frame(path)

    def context_menu(self, pos):
        """The menu a right click at pos in the tree shows, or None.

        The same as for nodes in the graph, with the row's node added to
        the selection first, or made the selection when it was not in it.
        """
        item = self.tree.itemAt(pos)
        path = item.data(0, PATH_ROLE) if item else None
        view = getattr(self.main_window, 'view', None)
        if not path or view is None or not self.stage_model:
            return None
        if path not in self.stage_model.selection:
            self.stage_model.set_selection([path])
        menu = view.node_menu(path, parent=self.tree)
        menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
        frame = QtWidgets.QAction('Frame in Graph', menu)
        frame.triggered.connect(
            lambda: self.stage_model.select_and_frame(path))
        first = menu.actions()[0] if menu.actions() else None
        menu.insertAction(first, frame)
        return menu

    def on_context_menu(self, pos):
        menu = self.context_menu(pos)
        if menu is not None:
            menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def on_collapsed(self, item):
        path = item.data(0, PATH_ROLE)
        if path and not self.search.text().strip():
            self.collapsed.add(path)

    def on_expanded(self, item):
        path = item.data(0, PATH_ROLE)
        if path:
            self.collapsed.discard(path)
