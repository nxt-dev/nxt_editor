"""The Instance View: a node's instance connections, and nothing else.

Pick a node, in the graph or the Outliner, and the Instance View draws the
nodes it instances from, back to the first, and every node that instances
it, and those that instance them in turn. Sources are to the left and
instances to the right, joined by the graph's instance lines.

Nodes are grey cards with their layers' colors in a strip along the top,
the strongest layer's across it and a chip for each weaker one at its
right end, as on the node in the graph. So it can be told from the graph
at a glance.

Follow Selection shows whatever node is selected, and Show Selected shows
it on demand while that is off. With Sync Selection on, nodes selected here
are selected in the graph and the Outliner too.
"""
# Builtin
import logging
from collections import OrderedDict

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
import nxt_editor
from nxt import nxt_path
from nxt_editor import colors, theme, user_dir
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

NODE_WIDTH = 220
NODE_HEIGHT = 50
STRIP = 6            # the layer colors along a node's top
CHIP = 10
COLUMN_GAP = 90
ROW_GAP = 22


def instance_sources(model):
    """Every node's instance source.

    :return: {node path: the path it instances}
    :rtype: dict
    """
    comp = model.comp_layer
    sources = {}
    for path in comp.descendants():
        source = model.get_node_instance_path(path, comp)
        if source and source != path:
            sources[path] = source
    return sources


def instance_lineage(model, node_path, sources=None):
    """The nodes node_path instances from, and that instance it, each with
    its column: negative for sources, 0 for the node, positive for
    instances.

    :return: ({path: column}, [(source, instance)])
    :rtype: (OrderedDict, list)
    """
    if sources is None:
        sources = instance_sources(model)
    instancers = {}
    for path, source in sorted(sources.items()):
        instancers.setdefault(source, []).append(path)
    columns = OrderedDict()
    columns[node_path] = 0
    links = []
    # Back to the first source.
    current, column = node_path, 0
    while current in sources:
        source = sources[current]
        if source in columns:
            break  # a loop
        column -= 1
        columns[source] = column
        links.append((source, current))
        current = source
    # Out to every instance, and theirs.
    queue = [node_path]
    while queue:
        path = queue.pop(0)
        for instance in instancers.get(path, ()):
            if instance in columns:
                continue
            columns[instance] = columns[path] + 1
            links.append((path, instance))
            queue.append(instance)
    return columns, links


def layer_colors(model, path):
    """The colors of the layers with an opinion on a node, strongest first.

    :rtype: list
    """
    layers = model.get_layers_with_opinion(path, as_layers=True) or []
    found = [model.get_layer_color(layer) for layer in layers]
    found = [color for color in found if color]
    if not found:
        found = [model.get_node_color(path) or '#808080']
    return found


def icon_button(icon, tooltip, checked_icon=None):
    """A button that is only an icon, its tooltip saying what it does. A
    toggle has a second icon for when it is on."""
    button = QtWidgets.QToolButton()
    button.setAutoRaise(True)
    button.setIconSize(QtCore.QSize(18, 18))
    button.setToolTip(tooltip)
    qicon = QtGui.QIcon()
    qicon.addPixmap(QtGui.QPixmap(':icons/icons/{}.png'.format(icon)),
                    QtGui.QIcon.Normal, QtGui.QIcon.Off)
    if checked_icon:
        button.setCheckable(True)
        qicon.addPixmap(
            QtGui.QPixmap(':icons/icons/{}.png'.format(checked_icon)),
            QtGui.QIcon.Normal, QtGui.QIcon.On)
    button.setIcon(qicon)
    return button


class InstanceNodeItem(QtWidgets.QGraphicsItem):
    """A grey card for a node, its layers' colors along the top."""

    def __init__(self, node_path, layer_colors_, exists=True, focus=False):
        super(InstanceNodeItem, self).__init__()
        self.node_path = node_path
        self.layer_colors = layer_colors_
        self.exists = exists
        self.focus = focus
        self.hovered = False
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setToolTip(node_path if exists else
                        node_path + '\nNot in the graph')

    def boundingRect(self):
        return QtCore.QRectF(-2, -2, NODE_WIDTH + 4, NODE_HEIGHT + 4)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)
        card = QtGui.QPainterPath()
        card.addRoundedRect(rect, theme.NODE_RADIUS, theme.NODE_RADIUS)
        body = theme.color(theme.RAISED)
        if not self.exists:
            body = theme.color(theme.BASE)
        painter.fillPath(card, body)
        # The layers, along the top: the strongest across it, a chip for
        # each weaker one at its right end.
        painter.save()
        painter.setClipPath(card)
        strip = QtCore.QRectF(0, 0, NODE_WIDTH, STRIP)
        painter.fillRect(strip, QtGui.QColor(self.layer_colors[0]))
        x = NODE_WIDTH
        for color in self.layer_colors[1:]:
            x -= CHIP
            painter.fillRect(QtCore.QRectF(x, 0, CHIP, STRIP),
                             QtGui.QColor(color))
        painter.restore()
        # Name, and the path to tell nodes of the same name apart.
        name = nxt_path.node_name_from_node_path(self.node_path)
        text_color = theme.color(theme.NODE_TEXT if self.exists
                                 else theme.TEXT_DIM)
        name_font = theme.font(theme.TEXT_PX + 1, QtGui.QFont.DemiBold)
        painter.setFont(name_font)
        painter.setPen(text_color)
        text_rect = QtCore.QRectF(10, STRIP + 4, NODE_WIDTH - 20, 20)
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter,
                         QtGui.QFontMetrics(name_font).elidedText(
                             name, QtCore.Qt.ElideRight,
                             int(text_rect.width())))
        path_font = theme.font(theme.SMALL_PX)
        painter.setFont(path_font)
        painter.setPen(theme.color(theme.TEXT_DIM))
        path_rect = QtCore.QRectF(10, STRIP + 24, NODE_WIDTH - 20, 16)
        painter.drawText(path_rect, QtCore.Qt.AlignVCenter,
                         QtGui.QFontMetrics(path_font).elidedText(
                             self.node_path, QtCore.Qt.ElideLeft,
                             int(path_rect.width())))
        # Edges: amber selected, white under the mouse, and a light one on
        # the node the view is about.
        edge = None
        if self.isSelected():
            edge = QtGui.QPen(colors.SELECTED, 2)
        elif self.hovered:
            edge = QtGui.QPen(theme.color(theme.HOVERED, 0.55), 1)
        elif self.focus:
            edge = QtGui.QPen(theme.color(theme.TEXT_DIM), 1)
        if edge is not None:
            painter.setPen(edge)
            painter.setBrush(QtCore.Qt.NoBrush)
            inset = edge.widthF() / 2.0
            painter.drawRoundedRect(rect.adjusted(inset, inset, -inset,
                                                  -inset),
                                    theme.NODE_RADIUS, theme.NODE_RADIUS)


class InstanceLinkItem(QtWidgets.QGraphicsPathItem):
    """An instance line from a source to a node instancing it, drawn as
    the graph draws them."""

    def __init__(self, source_item, instance_item):
        super(InstanceLinkItem, self).__init__()
        self.source_item = source_item
        self.instance_item = instance_item
        pen = QtGui.QPen(QtCore.Qt.gray, 2, QtCore.Qt.DashDotDotLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        start = self.source_item.pos() + QtCore.QPointF(NODE_WIDTH,
                                                        NODE_HEIGHT / 2.0)
        end = self.instance_item.pos() + QtCore.QPointF(0, NODE_HEIGHT / 2.0)
        bend = max(abs(end.x() - start.x()) * 0.5, 40)
        path = QtGui.QPainterPath(start)
        path.cubicTo(start + QtCore.QPointF(bend, 0),
                     end - QtCore.QPointF(bend, 0), end)
        self.setPath(path)


class InstanceGraphicsView(QtWidgets.QGraphicsView):
    """The Instance View's graph: zoom with the wheel, pan with the middle
    mouse button, box select, F frames, double click a node to show its
    instances."""
    focus_requested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(InstanceGraphicsView, self).__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(theme.color(theme.GRAPH))
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._pan_from = None

    def frame_all(self):
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-40, -40, 40, 40),
                       QtCore.Qt.KeepAspectRatio)
        # Never larger than life.
        if self.transform().m11() > 1.0:
            self.resetTransform()
            self.centerOn(rect.center())

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._pan_from = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            return
        super(InstanceGraphicsView, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_from is not None:
            delta = event.pos() - self._pan_from
            self._pan_from = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            return
        super(InstanceGraphicsView, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._pan_from = None
            self.unsetCursor()
            return
        super(InstanceGraphicsView, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, InstanceNodeItem) and item.exists:
            self.focus_requested.emit(item.node_path)
            return
        super(InstanceGraphicsView, self).mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_F:
            self.frame_all()
            return
        super(InstanceGraphicsView, self).keyPressEvent(event)


class InstanceView(DockWidgetBase):
    """A node's instance connections, forwards and backwards."""

    def __init__(self, parent=None):
        super(InstanceView, self).__init__(title='Instance View',
                                           parent=parent, minimum_width=200)
        self.main_window = parent
        main = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(main)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(2)
        self.show_button = icon_button(
            'instance_node', 'Show Selected: show the instance connections '
            'of the selected node.')
        self.show_button.clicked.connect(self.show_selected)
        bar.addWidget(self.show_button)
        self.follow_button = icon_button(
            'locate_off', 'Follow Selection: show the instance connections '
            'of whichever node is selected, as it is selected.',
            checked_icon='locate_on')
        self.follow_button.setChecked(bool(user_dir.user_prefs.get(
            user_dir.USER_PREF.INSTANCE_VIEW_FOLLOW, True)))
        self.follow_button.toggled.connect(self.on_follow_toggled)
        bar.addWidget(self.follow_button)
        self.sync_button = icon_button(
            'link', 'Sync Selection: select and frame the nodes picked here '
            'in the graph and the Outliner too.', checked_icon='link_pressed')
        self.sync_button.setChecked(bool(user_dir.user_prefs.get(
            user_dir.USER_PREF.INSTANCE_VIEW_SYNC, False)))
        self.sync_button.toggled.connect(self.on_sync_toggled)
        bar.addWidget(self.sync_button)
        bar.addStretch()
        layout.addLayout(bar)
        self.view = InstanceGraphicsView(main)
        self.view.focus_requested.connect(self.set_focus_path)
        self.view.scene().selectionChanged.connect(self.on_view_selection)
        layout.addWidget(self.view, 1)
        self.message = QtWidgets.QLabel(self.view)
        self.message.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        self.message.move(12, 10)
        self.setWidget(main)
        # The node shown, its graph's items by path, and the links.
        self.focus_path = None
        self.items = {}
        self.links = []
        # Selecting in the graph because of a selection here, so it is not
        # taken as a new node to show.
        self._pushing = False
        self._pulling = False
        self._stale = True
        self.rebuild_timer = QtCore.QTimer(self)
        self.rebuild_timer.setSingleShot(True)
        self.rebuild_timer.setInterval(0)
        self.rebuild_timer.timeout.connect(self.rebuild)
        self.show_message('Select a node to see its instances.')

    # Model --------------------------------------------------------------

    def set_stage_model(self, model):
        super(InstanceView, self).set_stage_model(model)
        self.focus_path = None
        if model is not None and model.selection:
            self.focus_path = model.selection[-1]
        self.request_rebuild()

    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.comp_layer_changed, self.request_rebuild),
            (model.nodes_changed, self.request_rebuild),
            (model.layer_color_changed, self.request_rebuild),
            (model.selection_changed, self.on_model_selection),
        ]
        super(InstanceView, self).set_stage_model_connections(model, connect)

    def on_stage_model_destroyed(self):
        super(InstanceView, self).on_stage_model_destroyed()
        self.rebuild_timer.stop()
        self.clear()

    # Showing a node ------------------------------------------------------

    def show_selected(self):
        """Show the instance connections of the selected node."""
        if self.stage_model and self.stage_model.selection:
            self.set_focus_path(self.stage_model.selection[-1])

    def set_focus_path(self, node_path):
        self.focus_path = node_path
        self.request_rebuild()

    def request_rebuild(self, *args):
        if not self.isVisible():
            # Hidden, there is nobody to draw for. Shown, it catches up.
            self._stale = True
            return
        self.rebuild_timer.start()

    def showEvent(self, event):
        super(InstanceView, self).showEvent(event)
        if self._stale:
            self.request_rebuild()

    def clear(self):
        self.view.scene().clear()
        self.items = {}
        self.links = []

    def show_message(self, text):
        self.message.setText(text)
        self.message.adjustSize()
        self.message.setVisible(bool(text))

    def rebuild(self):
        self._stale = False
        self.clear()
        model = self.stage_model
        path = self.focus_path
        if not model or not path:
            self.show_message('Select a node to see its instances.')
            return
        if not (model.node_exists(path) or model.node_is_implied(path)):
            self.show_message('{} is not in the graph.'.format(path))
            return
        columns, links = instance_lineage(model, path)
        by_column = OrderedDict()
        for node_path, column in columns.items():
            by_column.setdefault(column, []).append(node_path)
        for column, paths in by_column.items():
            height = len(paths) * (NODE_HEIGHT + ROW_GAP) - ROW_GAP
            for row, node_path in enumerate(paths):
                exists = model.node_exists(node_path)
                item = InstanceNodeItem(
                    node_path,
                    layer_colors(model, node_path) if exists else ['#555555'],
                    exists=exists, focus=node_path == path)
                item.setPos(column * (NODE_WIDTH + COLUMN_GAP),
                            row * (NODE_HEIGHT + ROW_GAP) - height / 2.0)
                self.view.scene().addItem(item)
                self.items[node_path] = item
        for source, instance in links:
            link = InstanceLinkItem(self.items[source], self.items[instance])
            self.view.scene().addItem(link)
            self.links.append(link)
        if links:
            self.show_message('')
        else:
            self.show_message('{} has no instance connections.'.format(
                nxt_path.node_name_from_node_path(path)))
        if self.sync_button.isChecked():
            self.pull_selection(model.selection)
        self.view.frame_all()

    # Selection -----------------------------------------------------------

    def on_follow_toggled(self, state):
        user_dir.user_prefs[user_dir.USER_PREF.INSTANCE_VIEW_FOLLOW] = state
        if state:
            self.show_selected()

    def on_sync_toggled(self, state):
        user_dir.user_prefs[user_dir.USER_PREF.INSTANCE_VIEW_SYNC] = state
        if state:
            self.on_view_selection()

    def on_model_selection(self, paths=()):
        if self._pushing:
            # Selected from here.
            return
        paths = list(paths or ())
        if self.follow_button.isChecked() and paths:
            if paths[-1] != self.focus_path:
                self.set_focus_path(paths[-1])
                return
        if self.sync_button.isChecked():
            self.pull_selection(paths)

    def pull_selection(self, paths):
        """Select the shown nodes selected in the graph."""
        self._pulling = True
        try:
            for node_path, item in self.items.items():
                item.setSelected(node_path in paths)
        finally:
            self._pulling = False

    def selected_paths(self):
        return [item.node_path for item in self.view.scene().selectedItems()
                if isinstance(item, InstanceNodeItem) and item.exists]

    def on_view_selection(self):
        """Nodes selected here are selected in the graph and the Outliner
        too, while Sync Selection is on."""
        if self._pulling or not self.sync_button.isChecked():
            return
        if not self.stage_model:
            return
        paths = self.selected_paths()
        if not paths:
            return
        self._pushing = True
        try:
            # Framed in the graph, opening what they are collapsed in, and
            # the Outliner opens and scrolls to their rows.
            self.stage_model.select_and_frame_nodes(paths)
        finally:
            self._pushing = False
