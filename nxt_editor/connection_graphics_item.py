# Built-in
import logging

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
from . import colors
from nxt import nxt_path, nxt_node
import nxt_editor
from nxt_editor import wires
from nxt_editor.node_graphics_item import MIN_LOD

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

# How far a curve leaves and meets its ends going straight across, as a
# share of the distance across, and never less than this many pixels.
CURVE_PULL = 0.5
CURVE_MIN_PULL = 40.0
# How close a double click has to be to a line to land on it.
HIT_WIDTH = 10.0
# Which way a curved line passes through an anchor: going right, as it
# leaves an out plug and meets an in plug, or going left.
RIGHT = 1
LEFT = -1
# How far the line's ends have to cross before a point turns round, so it
# does not flip back and forth as something is dragged past.
TURN_MARGIN = 8.0


def point_direction(previous, following, direction=None):
    """Which way a curved line passes through a point: going right while
    the anchor it goes on to is to the right of the one it comes from, and
    going left once it is to the left. The point's own place does not
    matter. It turns round only once they cross by TURN_MARGIN.

    :param previous: QPointF, the anchor the line comes from
    :param following: QPointF, the anchor the line goes on to
    :param direction: RIGHT or LEFT, the way it passes now, or None
    :return: RIGHT or LEFT
    """
    across = following.x() - previous.x()
    if direction is None:
        return RIGHT if across >= 0 else LEFT
    if direction == RIGHT and across < -TURN_MARGIN:
        return LEFT
    if direction == LEFT and across > TURN_MARGIN:
        return RIGHT
    return direction


def line_path(anchors, curved, directions=None):
    """The path a line takes through its anchors.

    Straight, it is a line from each anchor to the next. Curved, each piece
    leaves and arrives going across, the way it leaves an out plug and
    meets an in plug, so it bends smoothly through every point. A point
    the line runs through going left is left and arrived at going left.

    :param anchors: QPointFs, the source first and the target last
    :param curved: bool
    :param directions: RIGHT or LEFT for each anchor, all RIGHT if None
    :return: QPainterPath
    """
    if directions is None:
        directions = [RIGHT] * len(anchors)
    path = QtGui.QPainterPath(anchors[0])
    pieces = zip(anchors, anchors[1:], directions, directions[1:])
    for start, end, leaving, arriving in pieces:
        if not curved:
            path.lineTo(end)
            continue
        pull = max(abs(end.x() - start.x()) * CURVE_PULL, CURVE_MIN_PULL)
        path.cubicTo(QtCore.QPointF(start.x() + pull * leaving, start.y()),
                     QtCore.QPointF(end.x() - pull * arriving, end.y()), end)
    return path


class AttrConnectionGraphic(QtWidgets.QGraphicsPathItem):
    """Attribute connection graphics display the presence of "source_path"
    in the "target_path" attribute.

    The line is routed through its points, see nxt_editor.wires, and drawn
    straight or curved as the graph says.
    """
    ATTR_THICKNESS = 1.5
    EXEC_THICKNESS = 3
    # INFLATE_MULT = 1.7

    def __init__(self, model, view, source_path='', target_path=''):
        super(AttrConnectionGraphic, self).__init__()
        # self.setAcceptHoverEvents(True)
        # self.is_hovered = False
        self.thickness = self.ATTR_THICKNESS
        self.color = QtCore.Qt.gray
        self.pen_style = QtCore.Qt.SolidLine

        self.model = model
        self.view = view
        # If both directions are not given, to the cursor is implied.
        if not (source_path or target_path):
            raise ValueError("Must initialize a connection graphic with at "
                             "least one path, source or target.")
        self.src_path = source_path
        self.tgt_path = target_path
        self.src_node_path = nxt_path.node_path_from_attr_path(self.src_path)
        self.src_attr_name = nxt_path.attr_name_from_attr_path(self.src_path)
        self.tgt_node_path = nxt_path.node_path_from_attr_path(self.tgt_path)
        self.tgt_attr_name = nxt_path.attr_name_from_attr_path(self.tgt_path)
        self.src_pos = QtCore.QPointF()
        self.tgt_pos = QtCore.QPointF()
        self.point_graphics = []
        self.calculate_draw_details()

    @property
    def key(self):
        """The name this line's points are saved under."""
        return wires.line_key(self.src_path, self.tgt_path)

    @property
    def points(self):
        """Where the line's points are drawn, in order, as QPointFs."""
        return [QtCore.QPointF(g.pos()) for g in self.point_graphics]

    def set_points(self, points):
        """Route the line through the given [x, y] points."""
        for graphic in self.point_graphics:
            if graphic.scene():
                graphic.scene().removeItem(graphic)
            else:
                graphic.setParentItem(None)
        self.point_graphics = []
        for point in points or ():
            graphic = WirePointGraphic(self)
            graphic.setPos(QtCore.QPointF(point[0], point[1]))
            self.point_graphics.append(graphic)
        self.rebuild_line()

    def calculate_draw_details(self):
        self.thickness = self.ATTR_THICKNESS
        self.color = QtCore.Qt.gray
        self.pen_style = QtCore.Qt.SolidLine
        if self.src_attr_name:
            disp_layer = self.model.comp_layer
            type_ = self.model.get_node_attr_type(self.src_node_path,
                                                  self.src_attr_name,
                                                  disp_layer)
            self.color = colors.ATTR_COLORS.get(type_, QtCore.Qt.gray)
        if self.tgt_path:
            if self.tgt_attr_name == nxt_node.INTERNAL_ATTRS.EXECUTE_IN:
                self.thickness = self.EXEC_THICKNESS
                self.color = QtCore.Qt.white
            elif self.tgt_attr_name == nxt_node.INTERNAL_ATTRS.INSTANCE_PATH:
                self.pen_style = QtCore.Qt.DashDotDotLine
            elif self.tgt_attr_name:
                if self.model.node_attr_value_is_complex(self.tgt_node_path,
                                                         self.tgt_attr_name):
                    self.pen_style = QtCore.Qt.DashLine
                # Verify if attr we're connecting to has multiple tokens
        else:
            src_attr_name = nxt_path.attr_name_from_attr_path(self.src_path)
            if not src_attr_name:
                self.thickness = self.EXEC_THICKNESS
                self.color = QtCore.Qt.white
        for graphic in self.point_graphics:
            graphic.update()
        self.rebuild_line()

    def rebuild_line(self):
        src_node = self.view.get_node_graphic(self.src_node_path)
        tgt_node = self.view.get_node_graphic(self.tgt_node_path)
        if src_node:
            self.src_pos = src_node.get_attr_out_pos(self.src_attr_name,
                                                     scene=True)
            if not self.src_pos:
                exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                self.src_pos = src_node.get_attr_out_pos(exec_attr,
                                                         scene=True)
        else:
            self.src_pos = self.view.mouse_scene_pos
        if tgt_node:
            self.tgt_pos = tgt_node.get_attr_in_pos(self.tgt_attr_name,
                                                    scene=True)
            if not self.tgt_pos:
                exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                self.tgt_pos = tgt_node.get_attr_in_pos(exec_attr,
                                                        scene=True)
        else:
            self.tgt_pos = self.view.mouse_scene_pos
        anchors = [QtCore.QPointF(self.src_pos)] + self.points + \
            [QtCore.QPointF(self.tgt_pos)]
        curved = self.view.connection_style == wires.CURVED
        # Each point keeps the way the line passes through it, and only
        # turns round once the anchors either side of it cross over.
        for previous, graphic, following in zip(anchors, self.point_graphics,
                                                anchors[2:]):
            graphic.direction = point_direction(previous, following,
                                                graphic.direction)
        directions = [RIGHT] + [g.direction for g in self.point_graphics] + \
            [RIGHT]
        self.setPath(line_path(anchors, curved, directions))
        # I don't want this
        self.update()

    def hit(self, scene_pos):
        """Whether a click at scene_pos is on the line, with some room."""
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(max(HIT_WIDTH, self.thickness))
        return stroker.createStroke(self.path()).contains(scene_pos)

    def paint(self, painter, option, widget):
        lod = QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(
            painter.worldTransform())
        if lod > MIN_LOD:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform)
            thick_mult = 1
            pen_style = self.pen_style
        else:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform, False)
            thick_mult = 3
            pen_style = QtCore.Qt.PenStyle.SolidLine
        pen = QtGui.QPen(self.color, self.thickness * thick_mult, pen_style)
        # if self.tgt_path in self.model.selection:
        #    pen.setColor(colors.SELECTED)
        # elif self.is_hovered:
        #    pen.setWidthF(self.INFLATE_MULT * self.thickness)
        self.setPen(pen)
        self.setBrush(QtCore.Qt.NoBrush)
        super(AttrConnectionGraphic, self).paint(painter, option, widget)

    # def hoverEnterEvent(self, event):
    #    self.is_hovered = True
    #    self.update()

    # def hoverLeaveEvent(self, event):
    #    self.is_hovered = False
    #    self.update()


class WirePointGraphic(QtWidgets.QGraphicsItem):
    """A point a line is routed through, drawn as a dot in the line's color.

    Points are moved, selected and removed by the stage view, which saves
    them through the model. See nxt_editor.wires.

    A point is the same size on screen at any zoom. Scaled with the graph
    it shrank to the width of its line when zoomed out, and could no
    longer be told apart from it.
    """
    RADIUS = 5.0

    def __init__(self, connection):
        # A child of the line, so it goes when the line does. The line sits
        # at the scene's origin and draws in scene positions, so a point's
        # position is its scene position too.
        super(WirePointGraphic, self).__init__(connection)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self.connection = connection
        self.selected = False
        # RIGHT or LEFT, the way the line passes through; set by the line.
        self.direction = None

    def boundingRect(self):
        size = self.RADIUS + 2
        return QtCore.QRectF(-size, -size, size * 2, size * 2)

    def shape(self):
        path = QtGui.QPainterPath()
        path.addEllipse(self.boundingRect())
        return path

    def set_selected(self, state):
        if state != self.selected:
            self.selected = state
            self.update()

    def paint(self, painter, option, widget):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color = QtGui.QColor(self.connection.color)
        if self.selected:
            ring = QtGui.QPen(colors.SELECTED, 2)
        else:
            # Dark, so the dot stands apart from the line running into it.
            ring = QtGui.QPen(colors.GRAPH_BG_COLOR, 2)
        painter.setPen(ring)
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QPointF(), self.RADIUS, self.RADIUS)
