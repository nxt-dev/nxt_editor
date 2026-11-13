# Builtin
import logging

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
import nxt_editor
from nxt import nxt_path
from nxt.nxt_layer import LayerReturnTypes
from nxt_editor import colors, node_search, theme
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt_editor.label_edit import NameEditDialog

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

PATH_ROLE = QtCore.Qt.UserRole
# The layer colors of a row, the strongest opinion first.
LAYERS_ROLE = QtCore.Qt.UserRole + 1
# A section heading's start node, or '' for the nodes in no build.
SECTION_ROLE = QtCore.Qt.UserRole + 2
# True on a row whose own name matches the search.
MATCH_ROLE = QtCore.Qt.UserRole + 3
# True on a disabled node's row.
DISABLED_ROLE = QtCore.Qt.UserRole + 4
# The node's points as the graph shows them, of START, SKIP and BREAK, in
# that order.
POINTS_ROLE = QtCore.Qt.UserRole + 5
START = 'start'
SKIP = 'skip'
BREAK = 'break'
# True on an instanced node's row: an instance, or made by one.
INSTANCED_ROLE = QtCore.Qt.UserRole + 6
POINT_NAMES = {START: 'Start point', SKIP: 'Skip point',
               BREAK: 'Breakpoint'}

NOT_IN_A_BUILD = 'Not in a build'
# How long after the last key a search runs.
SEARCH_DELAY_MS = 300


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
    """What was typed in the search box, or None when it searches for
    nothing. See node_search: * for anything, commas between names.

    :rtype: node_search.NodeSearch or None
    """
    return node_search.search_for(text)


class NodeTree(QtWidgets.QTreeWidget):
    """The Outliner's tree.

    Typing a letter in a tree jumps to the next row starting with it, but
    letters are the node hotkeys here, as in the graph, so that is off.
    The search box finds nodes instead.

    A row's arrow collapses or expands its node, as double clicking the
    row does, rather than only opening or closing the row.
    """
    # The item whose arrow was clicked, and the modifiers held.
    arrowClicked = QtCore.Signal(object, object)

    def keyboardSearch(self, text):
        pass

    def drawBranches(self, painter, rect, index):
        """Drawn in drawRow instead, once the row is done."""

    def drawRow(self, painter, option, index):
        """The row, then the space beside it with only its arrow, drawn last.
        Rows outline themselves when selected, and Qt filled the space
        beside a selected row with the selection's grey, over its arrow."""
        super(NodeTree, self).drawRow(painter, option, index)
        left = self.visualRect(index).left()
        rect = QtCore.QRect(option.rect.left(), option.rect.top(),
                            left - option.rect.left(), option.rect.height())
        if rect.width() <= 0:
            return
        painter.save()
        painter.fillRect(rect, theme.color(theme.BASE))
        item = self.itemFromIndex(index)
        if item is not None and item.childCount():
            name = 'branch_open' if item.isExpanded() else 'branch_closed'
            pixmap = QtGui.QPixmap(
                ':/dark_style/styles/dark/rc/{}.png'.format(name))
            if not pixmap.isNull():
                indent = self.indentation()
                space = QtCore.QRect(left - indent, rect.top(), indent,
                                     rect.height())
                size = pixmap.size() / max(pixmap.devicePixelRatio(), 1.0)
                target = QtCore.QRect(QtCore.QPoint(0, 0), size)
                target.moveCenter(space.center())
                painter.drawPixmap(target, pixmap)
        painter.restore()

    def arrow_at(self, pos):
        """The item whose expand arrow is at pos in the viewport, or None."""
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if not item.childCount():
            return None
        rect = self.visualRect(index)
        if rect.left() - self.indentation() <= pos.x() < rect.left():
            return item
        return None

    def mousePressEvent(self, event):
        item = None
        if event.button() == QtCore.Qt.LeftButton:
            item = self.arrow_at(event.pos())
        shift = bool(event.modifiers() & QtCore.Qt.ShiftModifier)
        # A node's arrow, or with Shift a group's: the group's arrow on its
        # own just opens and closes the group.
        if item is not None and (item.data(0, PATH_ROLE) or shift):
            self.arrowClicked.emit(item, event.modifiers())
            event.accept()
            return
        super(NodeTree, self).mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # The press already took care of a click on an arrow.
        if self.arrow_at(event.pos()) is not None:
            self.mousePressEvent(event)
            return
        super(NodeTree, self).mouseDoubleClickEvent(event)


class NodeRowDelegate(QtWidgets.QStyledItemDelegate):
    """Draws a row the way its node looks in the graph.

    The row is filled with the color of the layer with the strongest
    opinion, and each weaker layer with an opinion adds a chip of its color
    at the right end, as on the node's title bar. Section headings are
    plain text.
    """
    # Tall enough to read and to hit, as a node in the graph is.
    ROW_HEIGHT = 28
    CHIP = 14        # wide enough to tell the colors apart at a glance
    CHIP_GAP = 0      # side by side, as on the node
    # A start, skip or break point before the name.
    POINT = 10
    POINT_INSET = 5
    POINT_GAP = 3
    POINT_TEXT_GAP = 6

    def sizeHint(self, option, index):
        size = super(NodeRowDelegate, self).sizeHint(option, index)
        return QtCore.QSize(size.width(), max(size.height(), self.ROW_HEIGHT))

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
        # Hover and selection only outline the row, the node's color
        # stays as it is.
        fill = top
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.fillPath(path, fill)
        if index.data(INSTANCED_ROLE):
            # Striped, as an instanced node's title is in the graph.
            painter.save()
            painter.setClipPath(path)
            theme.paint_stripes(painter, rect, fill)
            painter.restore()
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
        # As on the node in the graph: selected is a thick amber edge,
        # under the mouse a thin white one.
        if selected:
            painter.setPen(QtGui.QPen(colors.SELECTED, 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
        elif hovered:
            painter.setPen(QtGui.QPen(theme.color(theme.HOVERED, 0.55), 1))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                                    4, 4)
        y = rect.center().y()
        # Start, skip and break points, in the graph's shapes and colors,
        # then the name.
        left = rect.left() + 10
        points = index.data(POINTS_ROLE) or ()
        if points:
            left = rect.left() + self.POINT_INSET
            edge = fill.darker(167)
            for point in points:
                self.paint_point(painter, point,
                                 QtCore.QPointF(left + self.POINT / 2.0, y),
                                 edge)
                left += self.POINT + self.POINT_GAP
            left += self.POINT_TEXT_GAP - self.POINT_GAP
        font = index.data(QtCore.Qt.FontRole) or option.font
        if index.data(MATCH_ROLE):
            font = QtGui.QFont(font)
            font.setBold(True)
        painter.setFont(font)
        # White on every layer color, as on the node in the graph.
        text_color = theme.color(theme.NODE_TEXT)
        if index.data(DISABLED_ROLE):
            text_color.setAlphaF(0.55)
        painter.setPen(text_color)
        text_rect = QtCore.QRectF(left, rect.top(),
                                  rect.right() - chips_width - 6 - left,
                                  rect.height())
        text = QtGui.QFontMetrics(font).elidedText(
            index.data(QtCore.Qt.DisplayRole) or '', QtCore.Qt.ElideRight,
            int(text_rect.width()))
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter, text)
        painter.restore()

    @staticmethod
    def paint_point(painter, point, center, edge):
        """A start point's triangle, a skip point's bar or a breakpoint's
        square, centered on center and outlined in edge so it shows on the
        row's color."""
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(edge, 1))
        x, y = center.x(), center.y()
        if point == START:
            painter.setBrush(colors.START_COLOR)
            painter.drawPolygon(QtGui.QPolygonF([
                QtCore.QPointF(x - 3.5, y - 4.5),
                QtCore.QPointF(x + 4.5, y),
                QtCore.QPointF(x - 3.5, y + 4.5)]))
        elif point == SKIP:
            painter.setBrush(colors.SKIP_COLOR)
            painter.drawRoundedRect(QtCore.QRectF(x - 5.5, y - 2.5, 11, 5),
                                    2.5, 2.5)
        elif point == BREAK:
            painter.setBrush(colors.BREAK_COLOR)
            painter.drawRoundedRect(QtCore.QRectF(x - 4.5, y - 4.5, 9, 9),
                                    1.5, 1.5)
        painter.restore()


class Outliner(DockWidgetBase):
    """The nodes of the graph as a tree.

    Root nodes are grouped by the build that runs them, one section for
    each start point and a last one for the rest, and listed in the order
    they run. Each node's children sit under it in their child order.
    Rows are drawn in the colors of the layers the node is on. Selection
    follows the graph both ways, double clicking a node frames it, and the
    search box finds nodes at any depth by name, with * for anything
    and commas between names.
    """

    # Node names, larger than other lists to read at a glance.
    ROW_TEXT_PX = 15

    def __init__(self, parent=None):
        super(Outliner, self).__init__(title='Outliner', parent=parent,
                                       minimum_width=150)
        main = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(main)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search nodes: arm*ctrl, leg')
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip('Show the nodes whose name has what you type '
                               'in it, and the nodes above them. * stands '
                               'for anything, commas separate names, and a '
                               '/ matches the whole path. Enter frames the '
                               'first match.')
        # Searched once typing stops, or on Enter, rather than on every
        # key: each search rebuilds the tree.
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(self.request_rebuild)
        self.search.textChanged.connect(self.on_search_edited)
        self.search.returnPressed.connect(self.frame_first_match)
        layout.addWidget(self.search)
        self.tree = NodeTree()
        self.tree.setFont(theme.font(self.ROW_TEXT_PX))
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setMouseTracking(True)
        self.tree.setItemDelegate(NodeRowDelegate(self.tree))
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        self.tree.itemDoubleClicked.connect(self.on_double_click)
        self.tree.arrowClicked.connect(self.on_arrow_click)
        self.tree.itemCollapsed.connect(self.on_collapsed)
        self.tree.itemExpanded.connect(self.on_expanded)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        layout.addWidget(self.tree)
        self.main_window = parent
        self.add_node_hotkeys()
        self.setWidget(main)
        self.start_icon = QtGui.QIcon(
            QtGui.QPixmap(':icons/icons/add_startpoint.png'))
        self.items = {}
        self.sections = {}
        self.matches = []
        self.point_sets = (set(), set(), set())
        # What the rows were built from, to tell an edit that changes the
        # tree's shape from one that only changes rows. {root: exec in}
        self.exec_inputs = {}
        self._syncing = False
        # Several model signals can arrive for one edit, so the tree is
        # rebuilt once Qt is idle rather than for each of them.
        self.rebuild_timer = QtCore.QTimer(self)
        self.rebuild_timer.setSingleShot(True)
        self.rebuild_timer.setInterval(0)
        self.rebuild_timer.timeout.connect(self.rebuild)

    def set_stage_model(self, model):
        super(Outliner, self).set_stage_model(model)
        self.request_rebuild()

    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.comp_layer_changed, self.request_rebuild),
            (model.nodes_changed, self.on_nodes_changed),
            (model.starts_changed, self.request_rebuild),
            (model.breaks_changed, self.refresh_points),
            (model.skips_changed, self.refresh_points),
            (model.layer_color_changed, self.request_rebuild),
            (model.selection_changed, self.on_model_selection),
            (model.collapse_changed, self.on_collapse_changed),
            (model.frame_items, self.reveal),
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
            # Read once for every row, rather than from the prefs per row.
            self.point_sets = self.read_points()
            self.exec_inputs = {}
            for start, roots in build_sections(model):
                heading = self.add_section(start)
                for root in roots:
                    self.add_item(root, heading, pattern)
                if not heading.childCount():
                    # Nothing in it matched the search.
                    self.tree.invisibleRootItem().removeChild(heading)
                    self.sections.pop(start or '', None)
            # Only once every row is in the tree: Qt ignores expanding a
            # row that is not in it yet.
            # Rows are open or closed as their nodes are in the graph.
            searching = pattern is not None
            for path, item in self.items.items():
                item.setExpanded(searching or
                                 not model.get_node_collapse(path))
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

    def add_item(self, path, parent_item, pattern=None):
        """Add a node's row and its children's, keeping only the rows that
        match the search, and the rows above them.

        :return: the row, or None when neither it nor anything under it
            matched
        """
        model = self.stage_model
        name = nxt_path.node_name_from_node_path(path)
        matched = pattern is None or pattern.matches(path)
        item = QtWidgets.QTreeWidgetItem()
        item.setText(0, name)
        item.setToolTip(0, path)
        item.setData(0, PATH_ROLE, path)
        if pattern is not None and matched:
            item.setData(0, MATCH_ROLE, True)
        self.fill_row(item, path)
        if nxt_path.get_path_depth(path) == 1:
            self.exec_inputs[path] = model.get_node_exec_in(path)
        for child in model.get_children(path, ordered=True):
            self.add_item(child, item, pattern)
        if not matched and not item.childCount():
            return None
        parent_item.addChild(item)
        self.items[path] = item
        if pattern is not None and matched:
            self.matches.append(path)
        return item

    def fill_row(self, item, path):
        """Show on a row what can change without changing the tree: the
        node's layers, start, break and skip points, and whether it is
        enabled."""
        model = self.stage_model
        item.setData(0, LAYERS_ROLE, self.layer_colors(path))
        comp = model.comp_layer
        instanced = (model.get_node_is_proxy(path) or
                     model.get_node_instance(path, comp) is not None)
        item.setData(0, INSTANCED_ROLE, True if instanced else None)
        self.set_points(item, path)
        disabled = not model.get_node_enabled(path)
        item.setData(0, DISABLED_ROLE, True if disabled else None)
        font = item.font(0)
        font.setItalic(disabled)
        item.setFont(0, font)

    def read_points(self):
        """The paths of the graph's start, skip and break points.

        :rtype: (set, set, set)
        """
        model = self.stage_model
        return (set(model.get_start_nodes()), set(model.get_skippoints()),
                set(model.get_breakpoints()))

    def set_points(self, item, path):
        points = [point for point, paths
                  in zip((START, SKIP, BREAK), self.point_sets)
                  if path in paths]
        item.setData(0, POINTS_ROLE, points or None)
        names = ', '.join(POINT_NAMES[point] for point in points)
        item.setToolTip(0, path + ('\n' + names if names else ''))

    def refresh_points(self, *args):
        """A break or skip point changed: mark the rows, rather than build
        the tree again for it."""
        if not self.stage_model or not self.isVisible():
            # Shown again, the tree is built afresh.
            return
        if self.rebuild_timer.isActive():
            return
        self.point_sets = self.read_points()
        for path, item in self.items.items():
            self.set_points(item, path)

    def on_nodes_changed(self, paths=()):
        """Nodes were edited. The rows are filled in again where they are,
        unless the edit changed the tree: a node added, removed or moved,
        or a root's place in the builds."""
        if not self.stage_model or not self.isVisible():
            return
        if self.rebuild_timer.isActive():
            return
        if not self.shape_holds(paths):
            self.request_rebuild()
            return
        self.point_sets = self.read_points()
        for path in paths:
            item = self.items.get(path)
            if item is not None:
                self.fill_row(item, path)
        self.tree.viewport().update()

    def shape_holds(self, paths):
        """Whether the tree built last still has the shape of the graph
        where paths were edited."""
        model = self.stage_model
        if not paths or self.search.text().strip():
            # Which rows a search keeps can change with any edit.
            return False
        comp = model.comp_layer
        for path in paths:
            if path == nxt_path.WORLD:
                continue
            item = self.items.get(path)
            exists = comp.lookup(path) is not None
            if item is None or not exists:
                return False
            children = [item.child(i).data(0, PATH_ROLE)
                        for i in range(item.childCount())]
            if children != list(model.get_children(path, ordered=True)):
                return False
            if (nxt_path.get_path_depth(path) == 1 and
                    self.exec_inputs.get(path) !=
                    model.get_node_exec_in(path)):
                return False
        return True

    def reveal(self, paths=()):
        """Nodes were framed in the graph: open the group they are in and
        scroll to their rows. The graph opened any node they were collapsed
        in, and the rows followed it."""
        if not self.isVisible() or self.rebuild_timer.isActive():
            return
        last = None
        for path in paths or ():
            item = self.items.get(path)
            if item is None:
                continue
            top = item
            while top.parent() is not None:
                top = top.parent()
            if not top.isExpanded():
                top.setExpanded(True)
            last = item
        if last is not None:
            self.tree.scrollToItem(last)

    def on_search_edited(self, text):
        if not text.strip():
            # Cleared: everything comes back straight away.
            self.search_timer.stop()
            self.request_rebuild()
        else:
            self.search_timer.start()

    def frame_first_match(self):
        """Search now, then select and frame the first node found."""
        # Typing may have stopped and the tree not be rebuilt yet.
        if self.search_timer.isActive() or self.rebuild_timer.isActive():
            self.search_timer.stop()
            self.rebuild_timer.stop()
            self.rebuild()
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
            last = item
        if last is not None:
            # Scrolling to a row opens the rows above it, and they stay as
            # their nodes are in the graph: go to the closest one showing.
            shown = last
            parent = last.parent()
            while parent is not None:
                if not parent.isExpanded():
                    shown = parent
                parent = parent.parent()
            self.tree.scrollToItem(shown)

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

    def add_node_hotkeys(self):
        """The graph's node hotkeys, working here too while the tree has
        focus: D disables, N adds, Del deletes, S sets a start point, F
        frames and so on. The graph's arrow keys are left out, the tree
        needs them to move between rows."""
        window = self.main_window
        for name in ('node_actions', 'execute_actions'):
            container = getattr(window, name, None)
            if container is not None:
                self.tree.addActions(container.actions())
        view_actions = getattr(window, 'view_actions', None)
        if view_actions is not None:
            self.tree.addAction(view_actions.frame_selection_action)

    def on_double_click(self, item, column=0):
        """Double click a row as you would its node: collapse or expand
        it, with Shift everything below it as well, or with Ctrl rename
        it, here in the row."""
        path = item.data(0, PATH_ROLE)
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if not self.stage_model:
            return
        if not path:
            if modifiers & QtCore.Qt.ShiftModifier:
                self.toggle_group(item)
            return
        if modifiers == QtCore.Qt.ControlModifier:
            self.rename(path)
            return
        self.toggle_collapse(path, modifiers)

    def on_arrow_click(self, item, modifiers):
        """A row's arrow does what double clicking the row does: collapse
        or expand its node, with Shift everything below it as well."""
        path = item.data(0, PATH_ROLE)
        if not self.stage_model:
            return
        if path:
            self.toggle_collapse(path, modifiers)
        elif modifiers & QtCore.Qt.ShiftModifier:
            self.toggle_group(item)

    def toggle_group(self, heading):
        """Collapse every node in a group, a build or the nodes in none, or
        expand them all when they all are, as one undo."""
        paths = []

        def gather(item):
            for i in range(item.childCount()):
                child = item.child(i)
                path = child.data(0, PATH_ROLE)
                if path and child.childCount():
                    paths.append(path)
                gather(child)
        gather(heading)
        if not paths:
            return
        model = self.stage_model
        collapse = not all(model.get_node_collapse(p) for p in paths)
        heading.setExpanded(True)
        # The rows follow, see on_collapse_changed.
        model.set_node_collapse(paths, collapse)

    def toggle_collapse(self, path, modifiers):
        recursive = bool(modifiers & QtCore.Qt.ShiftModifier)
        # The rows follow, see on_collapse_changed.
        self.stage_model.toggle_node_collapse([path],
                                              recursive_down=recursive)

    def on_collapse_changed(self, paths):
        """Open or close the rows of nodes collapsed or expanded anywhere,
        so the tree shows what the graph does."""
        if self.search.text().strip():
            # A search shows every row it keeps.
            return
        syncing = self._syncing
        self._syncing = True
        try:
            for path in paths or ():
                item = self.items.get(path)
                if item is not None:
                    item.setExpanded(
                        not self.stage_model.get_node_collapse(path))
        finally:
            self._syncing = syncing

    def rename_selected(self):
        """Rename the first selected node, in its row."""
        selection = self.stage_model.selection if self.stage_model else []
        if selection:
            self.rename(selection[0])

    def rename(self, path):
        """Rename a node in a box over its row, like renaming it in the
        graph."""
        item = self.items.get(path)
        if item is None:
            return
        self.tree.scrollToItem(item)
        rect = self.tree.visualItemRect(item)
        top_left = self.tree.viewport().mapToGlobal(rect.topLeft())
        geometry = QtCore.QRect(top_left.x(), top_left.y(),
                                max(rect.width(), 120), rect.height())
        dialog = NameEditDialog(name=item.text(0), geometry=geometry,
                                parent=None)
        color = (item.data(0, LAYERS_ROLE) or ['#808080'])[0]
        dialog.line_edit.setStyleSheet(
            'background-color: %s; color: %s; border: 1px solid %s;' % (
                color, theme.NODE_TEXT, theme.SELECTED))
        dialog.line_edit.setFont(self.tree.font())
        dialog.exec_()
        if dialog.result() and dialog.value != item.text(0):
            self.stage_model.set_node_name(path, dialog.value,
                                           self.stage_model.target_layer)

    def context_menu(self, pos):
        """The menu a right click at pos in the tree shows, or None.

        The same as for nodes in the graph, with the row's node added to
        the selection first, or made the selection when it was not in it.
        Off the rows it is the graph's menu for empty space, to add or
        paste a node at the top of the hierarchy.
        """
        item = self.tree.itemAt(pos)
        path = item.data(0, PATH_ROLE) if item else None
        view = getattr(self.main_window, 'view', None)
        if view is None or not self.stage_model:
            return None
        if not path:
            if item is not None:
                # A section's heading.
                return None
            self.stage_model.set_selection([])
            return view.node_menu(None, parent=self.tree)
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
        self.row_opened(item, False)

    def on_expanded(self, item):
        self.row_opened(item, True)

    def row_opened(self, item, opened):
        """A row was opened or closed some way other than through its node,
        such as with the keyboard: do the same to the node, so the two never
        disagree."""
        path = item.data(0, PATH_ROLE)
        if (self._syncing or not path or not self.stage_model or
                self.search.text().strip()):
            # A search opens every row it keeps, for the search only.
            return
        if self.stage_model.get_node_collapse(path) == opened:
            self.stage_model.set_node_collapse([path], not opened)
