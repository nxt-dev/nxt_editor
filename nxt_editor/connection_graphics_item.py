# Built-in
import logging
import math

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
from . import colors
from nxt import nxt_path, nxt_node
import nxt_editor
from nxt_editor import user_dir, wires
from nxt_editor.node_graphics_item import MIN_LOD

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

# How far a curve leaves and meets its ends going straight across, as a
# share of the distance across, and never less than this many pixels.
CURVE_PULL = 0.5
CURVE_MIN_PULL = 40.0
# How close a double click has to be to a line to land on it, across
# both sides, in scene units.
HIT_WIDTH = 10.0
# How close a click has to be to a line on screen, each side, whatever the
# zoom, so a line is as easy to click zoomed out as in, and whichever way
# it runs.
HIT_PIXELS = 8.0


def path_distance(path, pos):
    """How far pos is from the nearest point on path, measured along
    points a few units apart."""
    length = path.length()
    steps = int(min(max(length / 3.0, 16), 4000))
    best = None
    for i in range(steps + 1):
        point = path.pointAtPercent(i / float(steps))
        gap = math.hypot(point.x() - pos.x(), point.y() - pos.y())
        if best is None or gap < best:
            best = gap
    return best if best is not None else float('inf')
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


# The kinds of line. Exec lines always show; each of the others can be
# hidden.
EXEC_LINES = 'exec'
PROPERTY_LINES = 'property'
INSTANCE_LINES = 'instance'
CODE_LINES = 'code'
LINE_KINDS = (EXEC_LINES, PROPERTY_LINES, INSTANCE_LINES, CODE_LINES)
# The preference each kind of line that can be hidden is shown or hidden by.
LINE_PREFS = {
    PROPERTY_LINES: user_dir.USER_PREF.SHOW_PROPERTY_LINES,
    INSTANCE_LINES: user_dir.USER_PREF.SHOW_INSTANCE_LINES,
    CODE_LINES: user_dir.USER_PREF.SHOW_CODE_LINES,
}


def lines_shown(kind=None):
    """Whether lines of a kind, one of LINE_KINDS, are turned on. All are
    until turned off, and exec lines can't be. With no kind, whether lines
    other than exec lines are shown at all, which hides those without
    changing which kinds are on.
    """
    if kind == EXEC_LINES:
        return True
    prefs = user_dir.user_prefs
    if kind is None:
        return prefs.get(user_dir.USER_PREF.SHOW_LINES) is not False
    shown = prefs.get(LINE_PREFS[kind])
    if shown is None and kind in (INSTANCE_LINES, CODE_LINES):
        # Hidden together before each had a toggle of its own.
        shown = prefs.get(user_dir.USER_PREF.SHOW_IMPLICIT)
    return shown is not False


def show_lines(kind, shown):
    """Turn lines of a kind on or off, or with kind None, all lines but
    exec lines, from now on and in every graph."""
    if kind == EXEC_LINES:
        raise ValueError('Exec lines are always shown.')
    if kind is None:
        key = user_dir.USER_PREF.SHOW_LINES
    else:
        key = LINE_PREFS[kind]
    user_dir.user_prefs[key] = bool(shown)


# A property line into a property the node inherits, rather than one set on
# the node itself, is dotted: round dots, in pen widths.
INHERITED_DOTS = [0.1, 2.5]

# Instance lines: thick, blue, long dashes with round ends, and the only
# lines with an arrow, at the node that is the instance. Dashes are in pen
# widths, the arrow in pixels.
INSTANCE_THICKNESS = 3.0
INSTANCE_DASHES = [3.0, 3.0]
INSTANCE_FAR_DASHES = [2.0, 1.5]
ARROW_LENGTH = 11.0
ARROW_WIDTH = 10.0
# How far short of the plug's middle the arrow's tip stops.
ARROW_GAP = 7.0


def instance_pen(scale=1.0, far=False):
    """The pen instance lines are drawn with.

    :param scale: how many times thicker than usual
    :param far: True when zoomed out, where the dashes are longer and
        square ended
    """
    pen = QtGui.QPen(colors.INSTANCE_LINE, INSTANCE_THICKNESS * scale)
    pen.setStyle(QtCore.Qt.CustomDashLine)
    pen.setDashPattern(INSTANCE_FAR_DASHES if far else INSTANCE_DASHES)
    pen.setCapStyle(QtCore.Qt.FlatCap if far else QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    return pen


def _unit(vector):
    length = (vector.x() ** 2 + vector.y() ** 2) ** 0.5 or 1.0
    return QtCore.QPointF(vector.x() / length, vector.y() / length)


def arrow_head(tip, direction, scale=1.0):
    """A filled arrowhead pointing along direction, its tip at tip.

    :param tip: QPointF
    :param direction: QPointF, the way the line arrives, any length
    :return: (QPolygonF, QPointF where its base meets the line)
    """
    along = _unit(direction)
    across = QtCore.QPointF(-along.y(), along.x())
    base = tip - along * ARROW_LENGTH * scale
    half = ARROW_WIDTH * scale / 2.0
    return (QtGui.QPolygonF([tip, base + across * half,
                             base - across * half]), base)


def arrow_line(anchors, curved, directions=None, scale=1.0):
    """A line through its anchors that ends in an arrow at the last one.

    The line stops at the arrow's base, so its dashes do not run into it.

    :return: (QPainterPath, QPolygonF)
    """
    end = anchors[-1]
    if curved:
        # A curved line always arrives going right.
        arriving = QtCore.QPointF(1.0, 0.0)
    else:
        arriving = end - anchors[-2]
    tip = end - _unit(arriving) * ARROW_GAP
    arrow, base = arrow_head(tip, arriving, scale)
    return line_path(list(anchors[:-1]) + [base], curved, directions), arrow


def paint_arrow_line(painter, path, arrow, pen):
    """Draw an instance line and its arrow, the dashes timed to end on a
    whole dash where the line meets the arrow."""
    dashes = pen.dashPattern()
    width = pen.widthF()
    if len(dashes) == 2 and width:
        dash, period = dashes[0] * width, (dashes[0] + dashes[1]) * width
        pen.setDashOffset(((dash - path.length()) % period) / width)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawPath(path)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(pen.color())
    painter.drawPolygon(arrow)


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
        self._anchors, self._directions, self._curved = [], None, False
        self.dashes = None
        # Set once the view draws it as one of the graph's lines, rather
        # than one being dragged out.
        self.drawn = False
        self.calculate_draw_details()

    @property
    def is_instance(self):
        return self.tgt_attr_name == nxt_node.INTERNAL_ATTRS.INSTANCE_PATH

    @property
    def kind(self):
        """Which kind of line this is, one of LINE_KINDS."""
        attr = self.tgt_attr_name
        if attr == nxt_node.INTERNAL_ATTRS.INSTANCE_PATH:
            return INSTANCE_LINES
        if attr == nxt_node.INTERNAL_ATTRS.COMPUTE:
            return CODE_LINES
        if attr == nxt_node.INTERNAL_ATTRS.EXECUTE_IN or not attr:
            return EXEC_LINES
        return PROPERTY_LINES

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
        self.dashes = None
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
            elif self.is_instance:
                self.thickness = INSTANCE_THICKNESS
                self.color = colors.INSTANCE_LINE
            elif self.tgt_attr_name and self.inherited():
                self.dashes = INHERITED_DOTS
        else:
            src_attr_name = nxt_path.attr_name_from_attr_path(self.src_path)
            if not src_attr_name:
                self.thickness = self.EXEC_THICKNESS
                self.color = QtCore.Qt.white
        for graphic in self.point_graphics:
            graphic.update()
        self.rebuild_line()

    def inherited(self):
        """Whether the property this line goes into comes from an instance
        or a parent, rather than being set on its node."""
        if self.kind != PROPERTY_LINES:
            return False
        source = self.model.get_node_attr_source_path(
            self.tgt_node_path, self.tgt_attr_name, self.model.comp_layer)
        return bool(source) and source != self.tgt_node_path

    def rebuild_line(self):
        src_node = self.view.get_node_graphic(self.src_node_path)
        tgt_node = self.view.get_node_graphic(self.tgt_node_path)
        if src_node:
            self.src_pos = src_node.get_attr_out_pos(self.src_attr_name,
                                                     scene=True)
            if not self.src_pos and self.is_instance:
                # Instance lines leave a little below exec lines, the
                # height they arrive at.
                self.src_pos = src_node.get_attr_out_pos(
                    nxt_node.INTERNAL_ATTRS.INSTANCE_PATH, scene=True)
            if not self.src_pos:
                exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                self.src_pos = src_node.get_attr_out_pos(exec_attr,
                                                         scene=True)
        else:
            self.src_pos = self.view.connection_drag_pos()
        if tgt_node:
            self.tgt_pos = tgt_node.get_attr_in_pos(self.tgt_attr_name,
                                                    scene=True)
            if not self.tgt_pos:
                exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                self.tgt_pos = tgt_node.get_attr_in_pos(exec_attr,
                                                        scene=True)
        else:
            self.tgt_pos = self.view.connection_drag_pos()
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
        self._anchors, self._directions = anchors, directions
        self._curved = curved
        self.setPath(line_path(anchors, curved, directions))
        if self.drawn:
            self.setVisible(self.view.line_shown(self))
        # I don't want this
        self.update()

    def hit(self, scene_pos, room=HIT_WIDTH / 2.0):
        """Whether a click at scene_pos is on the line, or within room of
        its edge."""
        return self.distance(scene_pos) <= room + self.thickness / 2.0

    def distance(self, scene_pos):
        """How far scene_pos is from the middle of the line."""
        return path_distance(self.path(), scene_pos)

    def shape(self):
        """Just the line. A path item's own shape takes in the space a
        bent line goes round as well, which would catch clicks there."""
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(self.thickness)
        return stroker.createStroke(self.path())

    def boundingRect(self):
        rect = super(AttrConnectionGraphic, self).boundingRect()
        if self.is_instance:
            # Room for the arrow, which is twice as big zoomed out.
            room = ARROW_WIDTH + INSTANCE_THICKNESS * 3
            rect = rect.adjusted(-room, -room, room, room)
        return rect

    def paint(self, painter, option, widget):
        lod = QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(
            painter.worldTransform())
        if self.is_instance and len(self._anchors) > 1:
            self.paint_instance(painter, lod > MIN_LOD)
            return
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
        if self.dashes and lod > MIN_LOD:
            pen.setDashPattern(self.dashes)
            pen.setCapStyle(QtCore.Qt.RoundCap)
        # if self.tgt_path in self.model.selection:
        #    pen.setColor(colors.SELECTED)
        # elif self.is_hovered:
        #    pen.setWidthF(self.INFLATE_MULT * self.thickness)
        self.setPen(pen)
        self.setBrush(QtCore.Qt.NoBrush)
        super(AttrConnectionGraphic, self).paint(painter, option, widget)

    def paint_instance(self, painter, near):
        """Long round dashes and an arrow, which stay when zoomed out so
        an instance line never looks like the others."""
        scale = 1.0 if near else 2.0
        painter.setRenderHint(QtGui.QPainter.Antialiasing, near)
        path, arrow = arrow_line(self._anchors, self._curved,
                                 self._directions, scale)
        paint_arrow_line(painter, path, arrow,
                         instance_pen(1.0 if near else 3.0, far=not near))

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
